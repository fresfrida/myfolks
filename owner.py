"""Who may use MyFolks. Terminal and Desktop are the owner; messaging must prove it."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from typing import Optional

from . import db

LOCAL_SURFACES = {"cli": "terminal", "tui": "terminal", "local": "terminal", "desktop": "Desktop"}
PRIVATE_CHAT = "dm"
SHARED_ACCESS = ("read", "add")
SHARED_SETTING = "shared_people"
FULL_ACCESS = "owner"
_TRUE_VALUES = {"1", "true", "yes", "on"}
_CODE_SETTING = "pairing_code"
CODE_LIFETIME_SECONDS = 600
MAX_ATTEMPTS = 5
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8


def local_surface(platform: Optional[str]) -> Optional[str]:
    return LOCAL_SURFACES.get((platform or "").strip().lower())


def messaging_label(platform: str) -> str:
    return platform.strip().capitalize()


def is_private_sender(source) -> bool:
    if source is None or getattr(source, "is_bot", False):
        return False
    return bool(getattr(source, "user_id", None)) and getattr(source, "chat_type", None) == PRIVATE_CHAT


def _split_ids(value: Optional[str]) -> set[str]:
    return {part.strip() for part in (value or "").split(",") if part.strip()}


def _secret(name: str) -> Optional[str]:
    if not name:
        return None
    try:
        from agent.secret_scope import get_secret

        return get_secret(name)
    except Exception:
        return None


def _entry_field(platform: str, field: str, fallback: str) -> str:
    try:
        from gateway.platform_registry import platform_registry

        entry = platform_registry.get(platform)
        return getattr(entry, field, "") or fallback
    except Exception:
        return fallback


def _config_allow_from(platform: str) -> set[str]:
    try:
        from gateway.config import Platform, load_gateway_config

        extra = load_gateway_config().platforms[Platform(platform)].extra
    except Exception:
        return set()
    value = extra.get("allow_from")
    if isinstance(value, str):
        return _split_ids(value)
    return {str(item).strip() for item in value or [] if str(item).strip()}


def allowed_users(platform: str) -> tuple[set[str], bool]:
    """Everyone Hermes lets in on this platform, and whether everyone is let in."""
    name = platform.strip().lower()
    upper = name.upper()
    allow_all_env = _entry_field(name, "allow_all_env", f"{upper}_ALLOW_ALL_USERS")
    open_to_all = any((_secret(env) or "").strip().lower() in _TRUE_VALUES for env in (allow_all_env, "GATEWAY_ALLOW_ALL_USERS"))
    users = _split_ids(_secret(_entry_field(name, "allowed_users_env", f"{upper}_ALLOWED_USERS")))
    users |= _split_ids(_secret("GATEWAY_ALLOWED_USERS"))
    users |= _config_allow_from(name)
    return users, open_to_all or "*" in users


def sole_allowed_user(platform: str) -> Optional[str]:
    users, open_to_all = allowed_users(platform)
    return next(iter(users)) if len(users) == 1 and not open_to_all else None


def is_paired_owner(connection: sqlite3.Connection, platform: str, user_id: str) -> bool:
    return bool(connection.execute("SELECT 1 FROM owners WHERE platform=? AND user_id=?", (platform, str(user_id))).fetchone())


def is_messaging_owner(vault, platform: str, source) -> bool:
    """True only for the owner's private chat. Any doubt is a no."""
    from .vault import VaultError

    if not is_private_sender(source):
        return False
    if sole_allowed_user(platform) == str(source.user_id):
        return True
    try:
        with vault.read() as connection:
            return is_paired_owner(connection, platform, str(source.user_id))
    except VaultError:
        return False


def shared_access(platform: str, source, entries) -> Optional[str]:
    """"read" or "add" for someone the owner shared with, else None. Private chats only."""
    if not is_private_sender(source):
        return None
    listed = entries.split(",") if isinstance(entries, str) else (entries or [])
    for entry in listed:
        parts = [part.strip() for part in str(entry).split(":")]
        if len(parts) == 3 and parts[0].lower() == platform and parts[1] == str(source.user_id) and parts[2].lower() in SHARED_ACCESS:
            return parts[2].lower()
    return None


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _clean_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def new_pairing_code(connection: sqlite3.Connection, *, clock=time.time) -> str:
    """Create a one-time code. Only its hash is stored."""
    code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
    db.set_setting(connection, _CODE_SETTING, json.dumps({"digest": _digest(code), "expires": clock() + CODE_LIFETIME_SECONDS, "attempts": 0}))
    return code


def _clear_code(connection: sqlite3.Connection) -> None:
    connection.execute("DELETE FROM settings WHERE key=?", (_CODE_SETTING,))


def try_pair(connection: sqlite3.Connection, platform: str, user_id: str, code: str, *, clock=time.time) -> bool:
    """Use a one-time code to make this sender the platform's owner."""
    stored = db.get_setting(connection, _CODE_SETTING)
    if not stored:
        return False
    record = json.loads(stored)
    if clock() > record["expires"]:
        _clear_code(connection)
        return False
    if not hmac.compare_digest(record["digest"], _digest(_clean_code(code))):
        record["attempts"] += 1
        if record["attempts"] >= MAX_ATTEMPTS:
            _clear_code(connection)
        else:
            db.set_setting(connection, _CODE_SETTING, json.dumps(record))
        return False
    _clear_code(connection)
    connection.execute("DELETE FROM owners WHERE platform=?", (platform,))
    connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES(?,?,?)", (platform, str(user_id), db.now()))
    return True
