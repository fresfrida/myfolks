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


def _touches_cards(connection: sqlite3.Connection, ops: list, card_ids: set[int]) -> bool:
    """Whether these row changes point at any of *card_ids*."""
    for op in ops:
        table, row_id = op[1], op[2]
        if table == "cards":
            found = row_id in card_ids
        elif table in ("details", "aliases"):
            row = connection.execute(f"SELECT card_id FROM {table} WHERE id=?", (row_id,)).fetchone()
            found = row is not None and row[0] in card_ids
        elif table == "links":
            row = connection.execute("SELECT from_card, to_card FROM links WHERE id=?", (row_id,)).fetchone()
            found = row is not None and (row[0] in card_ids or row[1] in card_ids)
        else:
            found = False
        if found:
            return True
    return False


def make_newest(connection: sqlite3.Connection, change_id: int) -> int:
    """Move a change to the end of the undo order, so the next undo reverses it first. It stays where it
    is when a newer change uses a card it created: newest-first undo then reverses that change first."""
    newer = connection.execute("SELECT ops FROM changes WHERE id>? AND undone_at IS NULL", (change_id,)).fetchall()
    if not newer:
        return change_id
    row = connection.execute("SELECT source,kind,summary,ops,undone_at FROM changes WHERE id=?", (change_id,)).fetchone()
    if row is None or row["undone_at"] is not None:
        return change_id
    created = {op[2] for op in json.loads(row["ops"]) if op[0] == "insert" and op[1] == "cards"}
    if any(_touches_cards(connection, json.loads(later["ops"]), created) for later in newer):
        return change_id
    cursor = connection.execute(
        "INSERT INTO changes(at,source,kind,summary,ops) VALUES(?,?,?,?,?)", (now(), row["source"], row["kind"], row["summary"], row["ops"])
    )
    connection.execute("DELETE FROM changes WHERE id=?", (change_id,))
    return cursor.lastrowid


class ChangeClosed(Exception):
    """A change can't be extended because it was undone."""


UNDO_TABLES = frozenset({"cards", "aliases", "details", "links", "review", "settings", "owners"})


class UndoBlocked(Exception):
    """Undoing would break something a later change still relies on. Nothing was changed."""

    def __init__(self, summary: str):
        super().__init__(summary)
        self.summary = summary


def undo_latest(connection: sqlite3.Connection) -> str | None:
    """Reverse the most recent change that has not been undone. Returns its summary.
    If the database refuses, nothing is changed and UndoBlocked says which change it was."""
    row = connection.execute("SELECT id,summary,ops FROM changes WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    ops = json.loads(row["ops"])
    if any(op[1] not in UNDO_TABLES for op in ops):
        raise UndoBlocked(row["summary"])  # names only MyFolks's own tables reach SQL
    connection.execute("SAVEPOINT myfolks_undo")
    try:
        for op in reversed(ops):
            if op[0] == "insert":
                connection.execute(f"DELETE FROM {op[1]} WHERE id=?", (op[2],))
            else:
                assignments = ",".join(f"{column}=?" for column in op[3])
                connection.execute(f"UPDATE {op[1]} SET {assignments} WHERE id=?", (*op[3].values(), op[2]))
        connection.execute("UPDATE changes SET undone_at=? WHERE id=?", (now(), row["id"]))
    except sqlite3.DatabaseError as exc:
        connection.execute("ROLLBACK TO myfolks_undo")
        connection.execute("RELEASE myfolks_undo")
        raise UndoBlocked(row["summary"]) from exc
    connection.execute("RELEASE myfolks_undo")
    return row["summary"]
