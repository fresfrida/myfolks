"""The device key: lives in the OS keychain when a real one is available, else in a 0600 file."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
from pathlib import Path
from typing import Optional

KEY_BYTES = 32
FILE_NAME = "device.key"
SERVICE = "MyFolks for Hermes"
_NOT_A_KEYCHAIN = ("keyring.backends.fail", "keyring.backends.null", "keyrings.alt")


def _is_os_keychain(backend) -> bool:
    children = getattr(backend, "backends", None)
    if children is not None:
        return bool(children) and _is_os_keychain(children[0])
    return not type(backend).__module__.startswith(_NOT_A_KEYCHAIN)


def _os_keyring():
    """The keyring module when it resolves to a real OS credential store, else None."""
    try:
        import keyring
    except ImportError:
        return None
    try:
        return keyring if _is_os_keychain(keyring.get_keyring()) else None
    except Exception:
        return None


class DeviceKeys:
    """Reads and writes one device key for one data folder."""

    def __init__(self, directory: Path, keyring_module=None, use_keychain: bool = True):
        self.directory = Path(directory)
        self._keyring = keyring_module if keyring_module is not None else (_os_keyring() if use_keychain else None)

    @property
    def file_path(self) -> Path:
        return self.directory / FILE_NAME

    @property
    def _account(self) -> str:
        return hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest()[:32]

    def load(self) -> Optional[bytes]:
        if self.file_path.exists():
            return self._decode(self.file_path.read_text(encoding="ascii"))
        if self._keyring is not None:
            try:
                stored = self._keyring.get_password(SERVICE, self._account)
            except Exception:
                return None
            return self._decode(stored) if stored else None
        return None

    def create(self) -> bytes:
        """Make a new device key, replacing any earlier one."""
        key = secrets.token_bytes(KEY_BYTES)
        encoded = base64.b64encode(key).decode("ascii")
        if self._keyring is not None and self._store_in_keychain(encoded):
            self.file_path.unlink(missing_ok=True)
            return key
        self._write_file(encoded)
        return key

    def _store_in_keychain(self, encoded: str) -> bool:
        try:
            self._keyring.set_password(SERVICE, self._account, encoded)
            return self._keyring.get_password(SERVICE, self._account) == encoded
        except Exception:
            return False

    def _write_file(self, encoded: str) -> None:
        temp = self.directory / f".{FILE_NAME}.{os.getpid()}.tmp"
        temp.unlink(missing_ok=True)
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(encoded + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.file_path)

    @staticmethod
    def _decode(encoded: str) -> Optional[bytes]:
        try:
            key = base64.b64decode(encoded.strip(), validate=True)
        except ValueError:
            return None
        return key if len(key) == KEY_BYTES else None
