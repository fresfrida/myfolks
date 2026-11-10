"""One encrypted file holding a whole SQLite database.

Every operation takes an exclusive lock, decrypts into in-memory SQLite, works, and for changes
encrypts and atomically replaces the file. Plaintext never touches the disk.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import sqlite3
import struct
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import db
from .device_key import DeviceKeys

MAGIC = b"MFLK"
FORMAT_VERSION = 1
_PREFIX = struct.Struct(">4sBI")
_MAX_HEADER_BYTES = 64 * 1024

STORE_NAME = "store.enc"
VERSIONS_DIR = "versions"
LOCK_NAME = "store.lock"
KEEP_VERSIONS = 7

KEY_BYTES = 32
NONCE_BYTES = 12
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
_SCRYPT_MAX_N = 2**20
_RECOVERY_BYTES = 20
_RECOVERY_CHARS = 32

_DEVICE_AAD = b"myfolks/device-wrap/v1"
_RECOVERY_AAD = b"myfolks/recovery-wrap/v1"


class VaultError(Exception):
    """Base class for store failures."""


class NotSetUp(VaultError):
    """No store exists yet."""


class AlreadySetUp(VaultError):
    """A store already exists."""


class Refused(VaultError):
    """Wrong key, wrong recovery code or a damaged file. The file is left untouched."""


class Busy(VaultError):
    """Another process held the lock for too long."""


def default_directory() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir("myfolks")


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def normalize_recovery_code(code: str) -> str:
    return re.sub(r"[^A-Z2-7]", "", code.upper())


def _new_recovery_code() -> str:
    raw = base64.b32encode(secrets.token_bytes(_RECOVERY_BYTES)).decode("ascii")
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


def _derive(code: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=KEY_BYTES, n=n, r=r, p=p).derive(normalize_recovery_code(code).encode("ascii"))


def _wrap(wrapping_key: bytes, data_key: bytes, aad: bytes) -> dict:
    nonce = secrets.token_bytes(NONCE_BYTES)
    return {"nonce": _b64(nonce), "ct": _b64(AESGCM(wrapping_key).encrypt(nonce, data_key, aad))}


def _unwrap(wrapping_key: bytes, wrapped: dict, aad: bytes) -> bytes:
    try:
        data_key = AESGCM(wrapping_key).decrypt(_unb64(wrapped["nonce"]), _unb64(wrapped["ct"]), aad)
    except (InvalidTag, KeyError, TypeError, ValueError) as exc:
        raise Refused("key does not open this store") from exc
    if len(data_key) != KEY_BYTES:
        raise Refused("key does not open this store")
    return data_key


def _sync_file(descriptor: int) -> None:
    if sys.platform == "darwin":
        import fcntl

        try:
            fcntl.fcntl(descriptor, fcntl.F_FULLFSYNC)
            return
        except OSError:
            pass
    os.fsync(descriptor)


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _try_lock(descriptor: int) -> bool:
    if os.name == "posix":
        import fcntl

        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False
    import msvcrt

    try:
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _unlock(descriptor: int) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)
    else:
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)


class Vault:
    def __init__(self, directory: Optional[Path] = None, keys: Optional[DeviceKeys] = None, lock_timeout: float = 10.0):
        self.directory = Path(directory) if directory is not None else default_directory()
        self.keys = keys if keys is not None else DeviceKeys(self.directory)
        self.lock_timeout = lock_timeout

    @property
    def store_path(self) -> Path:
        return self.directory / STORE_NAME

    @property
    def versions_path(self) -> Path:
        return self.directory / VERSIONS_DIR

    def exists(self) -> bool:
        return self.store_path.exists()

    def version_files(self) -> list[Path]:
        """Saved older copies, oldest first."""
        return sorted(self.versions_path.glob("*.enc")) if self.versions_path.is_dir() else []

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.directory / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            deadline = time.monotonic() + self.lock_timeout
            while not _try_lock(descriptor):
                if time.monotonic() >= deadline:
                    raise Busy("store is busy")
                time.sleep(0.01)
            try:
                yield
            finally:
                _unlock(descriptor)
        finally:
            os.close(descriptor)

    def setup(self) -> str:
        """Create the store and return the recovery code. The code is never stored."""
        with self._locked():
            if self.exists():
                raise AlreadySetUp("store already exists")
            data_key = secrets.token_bytes(KEY_BYTES)
            code = _new_recovery_code()
            device_key = self.keys.create()
            salt = secrets.token_bytes(16)
            recovery_key = _derive(code, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
            header = {
                "device": _wrap(device_key, data_key, _DEVICE_AAD),
                "recovery": {
                    "kdf": "scrypt",
                    "salt": _b64(salt),
                    "n": SCRYPT_N,
                    "r": SCRYPT_R,
                    "p": SCRYPT_P,
                    **_wrap(recovery_key, data_key, _RECOVERY_AAD),
                },
            }
            connection = self._connect()
            db.create_schema(connection)
            self._save(connection, data_key, header)
            return code

    def recover(self, code: str) -> None:
        """Open the store with the recovery code and bind it to a new device key."""
        with self._locked():
            header, nonce, ciphertext, prefix = self._read_file()
            recovery = header.get("recovery") or {}
            if len(normalize_recovery_code(code)) != _RECOVERY_CHARS:
                raise Refused("recovery code does not open this store")
            data_key = _unwrap(self._recovery_key(code, recovery), recovery, _RECOVERY_AAD)
            connection = self._decrypt(data_key, nonce, ciphertext, prefix)
            device_key = self.keys.create()
            self._save(connection, data_key, {**header, "device": _wrap(device_key, data_key, _DEVICE_AAD)})

    @staticmethod
    def _recovery_key(code: str, recovery: dict) -> bytes:
        try:
            n, r, p = int(recovery["n"]), int(recovery["r"]), int(recovery["p"])
            salt = _unb64(recovery["salt"])
        except (KeyError, TypeError, ValueError) as exc:
            raise Refused("store header is damaged") from exc
        if not (2 <= n <= _SCRYPT_MAX_N and r == SCRYPT_R and p == SCRYPT_P):
            raise Refused("store header is damaged")
        return _derive(code, salt, n, r, p)

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._locked():
            connection, _data_key, _header = self._open()
            try:
                yield connection
            finally:
                connection.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Yield the database; on clean exit, save it if anything changed."""
        with self._locked():
            connection, data_key, header = self._open()
            try:
                yield connection
                connection.commit()
                if connection.total_changes > 0:
                    self._save(connection, data_key, header)
            finally:
                connection.close()

    def _open(self) -> tuple[sqlite3.Connection, bytes, dict]:
        header, nonce, ciphertext, prefix = self._read_file()
        device_key = self.keys.load()
        if device_key is None:
            raise Refused("device key is missing")
        data_key = _unwrap(device_key, header.get("device") or {}, _DEVICE_AAD)
        return self._decrypt(data_key, nonce, ciphertext, prefix), data_key, header

    def _read_file(self) -> tuple[dict, bytes, bytes, bytes]:
        try:
            blob = self.store_path.read_bytes()
        except FileNotFoundError as exc:
            raise NotSetUp("no store yet") from exc
        try:
            magic, version, header_length = _PREFIX.unpack_from(blob)
        except struct.error as exc:
            raise Refused("store file is damaged") from exc
        body_start = _PREFIX.size + header_length
        if magic != MAGIC or version != FORMAT_VERSION or header_length > _MAX_HEADER_BYTES:
            raise Refused("store file is damaged")
        if len(blob) < body_start + NONCE_BYTES:
            raise Refused("store file is damaged")
        try:
            header = json.loads(blob[_PREFIX.size:body_start])
        except ValueError as exc:
            raise Refused("store file is damaged") from exc
        if not isinstance(header, dict):
            raise Refused("store file is damaged")
        nonce = blob[body_start : body_start + NONCE_BYTES]
        return header, nonce, blob[body_start + NONCE_BYTES :], blob[:body_start]

    def _decrypt(self, data_key: bytes, nonce: bytes, ciphertext: bytes, prefix: bytes) -> sqlite3.Connection:
        try:
            plaintext = AESGCM(data_key).decrypt(nonce, ciphertext, prefix)
        except InvalidTag as exc:
            raise Refused("store file is damaged or the key is wrong") from exc
        connection = self._connect()
        connection.deserialize(plaintext)
        db.configure(connection)
        db.check_schema(connection)
        return connection

    @staticmethod
    def _connect() -> sqlite3.Connection:
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        db.configure(connection)
        return connection

    def _save(self, connection: sqlite3.Connection, data_key: bytes, header: dict) -> None:
        connection.commit()
        header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
        prefix = _PREFIX.pack(MAGIC, FORMAT_VERSION, len(header_bytes)) + header_bytes
        nonce = secrets.token_bytes(NONCE_BYTES)
        ciphertext = AESGCM(data_key).encrypt(nonce, connection.serialize(), prefix)
        self._replace_store(prefix + nonce + ciphertext)

    def _replace_store(self, blob: bytes) -> None:
        self._remove_leftover_temps()
        temp = self.directory / f".{STORE_NAME}.{os.getpid()}.tmp"
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(blob)
                handle.flush()
                _sync_file(handle.fileno())
            self._keep_current_as_version()
            os.replace(temp, self.store_path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        _sync_directory(self.directory)
        self._prune_versions()

    def _remove_leftover_temps(self) -> None:
        for leftover in self.directory.glob(f".{STORE_NAME}.*.tmp"):
            leftover.unlink(missing_ok=True)

    def _keep_current_as_version(self) -> None:
        if not self.store_path.exists():
            return
        self.versions_path.mkdir(mode=0o700, exist_ok=True)
        target = self.versions_path / f"{time.time_ns():020d}.enc"
        try:
            os.link(self.store_path, target)
        except OSError:
            shutil.copy2(self.store_path, target)
        _sync_directory(self.versions_path)

    def _prune_versions(self) -> None:
        files = self.version_files()
        for old in files[: max(0, len(files) - KEEP_VERSIONS)]:
            old.unlink(missing_ok=True)
