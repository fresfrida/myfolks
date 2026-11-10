"""Passphrase-encrypted backups of the whole store. The database stays in memory throughout."""

from __future__ import annotations

import json
import secrets
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import cards

MAGIC = b"MFBK"
FORMAT_VERSION = 1
_PREFIX = struct.Struct(">4sBI")
_MAX_HEADER_BYTES = 4096
_NONCE_BYTES = 12
_KEY_BYTES = 32
_SCRYPT_N = 2**17
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAX_N = 2**20
MIN_PASSPHRASE = 8


class BackupRefused(Exception):
    """Wrong passphrase or a damaged backup."""


def _derive(passphrase: str, salt: bytes, n: int) -> bytes:
    return Scrypt(salt=salt, length=_KEY_BYTES, n=n, r=_SCRYPT_R, p=_SCRYPT_P).derive(passphrase.encode("utf-8"))


def seal(database: bytes, passphrase: str) -> bytes:
    salt = secrets.token_bytes(16)
    header = json.dumps({"kdf": "scrypt", "salt": salt.hex(), "n": _SCRYPT_N}, separators=(",", ":")).encode("utf-8")
    prefix = _PREFIX.pack(MAGIC, FORMAT_VERSION, len(header)) + header
    nonce = secrets.token_bytes(_NONCE_BYTES)
    return prefix + nonce + AESGCM(_derive(passphrase, salt, _SCRYPT_N)).encrypt(nonce, database, prefix)


def unseal(blob: bytes, passphrase: str) -> bytes:
    try:
        magic, version, length = _PREFIX.unpack_from(blob)
        body = _PREFIX.size + length
        if magic != MAGIC or version != FORMAT_VERSION or length > _MAX_HEADER_BYTES:
            raise ValueError("not a backup")
        header = json.loads(blob[_PREFIX.size:body])
        salt, n = bytes.fromhex(header["salt"]), int(header["n"])
        if not 2 <= n <= _SCRYPT_MAX_N:
            raise ValueError("bad parameters")
        nonce = blob[body : body + _NONCE_BYTES]
        return AESGCM(_derive(passphrase, salt, n)).decrypt(nonce, blob[body + _NONCE_BYTES :], blob[:body])
    except (InvalidTag, KeyError, TypeError, ValueError, struct.error) as exc:
        raise BackupRefused("cannot open this backup") from exc


def export_document(connection) -> dict:
    """Everything saved, readable, for the terminal-only plaintext export."""
    people = []
    for card in connection.execute("SELECT * FROM cards ORDER BY norm_name, id"):
        aliases = [row["alias"] for row in connection.execute("SELECT alias FROM aliases WHERE card_id=? ORDER BY id", (card["id"],))]
        lines = [
            {"text": line["text"], "saved_at": line["saved_at"], "source": line["source"], "closed_at": line["closed_at"], "private": bool(line["private"])}
            for line in cards.all_lines(connection, card["id"])
        ]
        links = [
            {"relation": link["relation"], "to": link["to_name"]}
            for link in cards.open_links(connection, card["id"])
            if link["from_card"] == card["id"]
        ]
        people.append({"name": card["name"], "kind": card["kind"], "aliases": aliases, "lines": lines, "links": links})
    return {"format": "myfolks-export", "version": 1, "cards": people}
