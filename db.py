"""Schema and the change log used for undo."""

from __future__ import annotations

from typing import Optional

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE cards(
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('person','pet','company','place')),
  name TEXT NOT NULL,
  norm_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL
);
CREATE INDEX cards_norm ON cards(norm_name);

CREATE TABLE aliases(
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  alias TEXT NOT NULL,
  norm_alias TEXT NOT NULL,
  automatic INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX aliases_norm ON aliases(norm_alias);
CREATE INDEX aliases_card ON aliases(card_id);

CREATE TABLE details(
  id INTEGER PRIMARY KEY,
  card_id INTEGER NOT NULL REFERENCES cards(id),
  field TEXT CHECK(field IS NULL OR field IN ('phone','email','birthday')),
  text TEXT NOT NULL,
  norm_value TEXT,
  birth_year INTEGER,
  birth_month INTEGER,
  birth_day INTEGER,
  saved_at TEXT NOT NULL,
  source TEXT NOT NULL,
  closed_at TEXT,
  replaces_id INTEGER REFERENCES details(id),
  private INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX details_card ON details(card_id, closed_at);
CREATE INDEX details_norm ON details(field, norm_value);

CREATE TABLE links(
  id INTEGER PRIMARY KEY,
  from_card INTEGER NOT NULL REFERENCES cards(id),
  relation TEXT NOT NULL,
  norm_relation TEXT NOT NULL,
  to_card INTEGER NOT NULL REFERENCES cards(id),
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  closed_at TEXT
);
CREATE INDEX links_from ON links(from_card, closed_at);
CREATE INDEX links_to ON links(to_card, closed_at);

CREATE TABLE changes(
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  ops TEXT NOT NULL,
  undone_at TEXT
);

CREATE TABLE review(
  id INTEGER PRIMARY KEY,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','merged','kept')),
  resolved_at TEXT
);

CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE owners(platform TEXT NOT NULL, user_id TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(platform, user_id));
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def configure(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.row_factory = sqlite3.Row


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(_SCHEMA)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    connection.commit()


def check_schema(connection: sqlite3.Connection) -> None:
    """Bring an older store up to date in memory, or refuse one this version can't read."""
    from .vault import Refused

    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == 1:
        connection.execute("ALTER TABLE details ADD COLUMN private INTEGER NOT NULL DEFAULT 0")
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        connection.commit()
        version = SCHEMA_VERSION
    if version != SCHEMA_VERSION:
        raise Refused("store version is not supported")


def get_setting(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
    )


class Change:
    """One undoable group of row changes."""

    def __init__(self, connection: sqlite3.Connection, kind: str, source: str):
        self.connection = connection
        self.kind = kind
        self.source = source
        self.ops: list[list] = []

    def insert(self, table: str, **values) -> int:
        columns = ",".join(values)
        marks = ",".join("?" for _ in values)
        cursor = self.connection.execute(f"INSERT INTO {table}({columns}) VALUES({marks})", tuple(values.values()))
        self.ops.append(["insert", table, cursor.lastrowid])
        return cursor.lastrowid

    def update(self, table: str, row_id: int, **values) -> None:
        columns = ",".join(values)
        before = self.connection.execute(f"SELECT {columns} FROM {table} WHERE id=?", (row_id,)).fetchone()
        assignments = ",".join(f"{column}=?" for column in values)
        self.connection.execute(f"UPDATE {table} SET {assignments} WHERE id=?", (*values.values(), row_id))
        self.ops.append(["update", table, row_id, dict(before)])

    def finish(self, summary: str) -> None:
        if not self.ops:
            return
        self.connection.execute(
            "INSERT INTO changes(at,source,kind,summary,ops) VALUES(?,?,?,?,?)",
            (now(), self.source, self.kind, summary, json.dumps(self.ops, separators=(",", ":"))),
        )

    def finish_into(self, summary: str, change_id: Optional[int]) -> Optional[int]:
        """Add this batch to an earlier change, so one undo reverses every batch. Returns the change id."""
        if change_id is None:
            if not self.ops:
                return None
            cursor = self.connection.execute(
                "INSERT INTO changes(at,source,kind,summary,ops) VALUES(?,?,?,?,?)",
                (now(), self.source, self.kind, summary, json.dumps(self.ops, separators=(",", ":"))),
            )
            return cursor.lastrowid
        row = self.connection.execute("SELECT ops, undone_at FROM changes WHERE id=?", (change_id,)).fetchone()
        if row is None or row["undone_at"] is not None:
            raise ChangeClosed("the earlier part was undone")
        if self.ops:
            ops = json.loads(row["ops"]) + self.ops
            self.connection.execute("UPDATE changes SET ops=?, summary=? WHERE id=?", (json.dumps(ops, separators=(",", ":")), summary, change_id))
        return change_id


def make_newest(connection: sqlite3.Connection, change_id: int) -> int:
    """Move a change to the end of the undo order, so the next undo reverses it first."""
    newer = connection.execute("SELECT 1 FROM changes WHERE id>? LIMIT 1", (change_id,)).fetchone()
    if newer is None:
        return change_id
    row = connection.execute("SELECT source,kind,summary,ops,undone_at FROM changes WHERE id=?", (change_id,)).fetchone()
    if row is None or row["undone_at"] is not None:
        return change_id
    cursor = connection.execute(
        "INSERT INTO changes(at,source,kind,summary,ops) VALUES(?,?,?,?,?)", (now(), row["source"], row["kind"], row["summary"], row["ops"])
    )
    connection.execute("DELETE FROM changes WHERE id=?", (change_id,))
    return cursor.lastrowid


class ChangeClosed(Exception):
    """A change can't be extended because it was undone."""


def undo_latest(connection: sqlite3.Connection) -> str | None:
    """Reverse the most recent change that has not been undone. Returns its summary."""
    row = connection.execute("SELECT id,summary,ops FROM changes WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    for op in reversed(json.loads(row["ops"])):
        if op[0] == "insert":
            connection.execute(f"DELETE FROM {op[1]} WHERE id=?", (op[2],))
        else:
            assignments = ",".join(f"{column}=?" for column in op[3])
            connection.execute(f"UPDATE {op[1]} SET {assignments} WHERE id=?", (*op[3].values(), op[2]))
    connection.execute("UPDATE changes SET undone_at=? WHERE id=?", (now(), row["id"]))
    return row["summary"]
