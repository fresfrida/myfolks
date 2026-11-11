"""Cards, aliases, details and links: reading and changing them."""

from __future__ import annotations

import re
import sqlite3
from typing import Optional

from . import db, fields
from .text import load_data, normalize, one_edit_apart

_RELATIONS = load_data("relations.json")
_EQUIVALENT = {word: set(group) for group in _RELATIONS["equivalent"] for word in group}
_KIND_OF = {word: kind for kind, words in _RELATIONS["kinds"].items() for word in words}
RELATION_WORDS = frozenset(
    {word for group in _RELATIONS["equivalent"] for word in group}
    | set(_RELATIONS["broader"]) | {word for words in _RELATIONS["broader"].values() for word in words}
    | set(_RELATIONS["inverse"]) | set(_KIND_OF)
)
_NAME_WORD = r"[A-Z][\w\u2019'-]*"
_OFFER = re.compile(
    r"(?<![\w'\u2019])(?i:(" + "|".join(sorted(map(re.escape, RELATION_WORDS), key=len, reverse=True)) + r"))"
    r"(?:['\u2019]s)?\s+(?i:name\s+is|name|is\s+called|is\s+named|is|named|called)\s+"
    r"(" + _NAME_WORD + r"(?:\s+" + _NAME_WORD + r"){0,2})"
)
_TRAILING_POSSESSIVE = re.compile(r"(?:['\u2019][sS]|['\u2019])$")


def find_cards(connection: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """Every card whose name or alias is exactly *name*, case-insensitive."""
    norm = normalize(name)
    return connection.execute(
        """SELECT DISTINCT cards.* FROM cards LEFT JOIN aliases ON aliases.card_id=cards.id
           WHERE cards.norm_name=? OR aliases.norm_alias=? ORDER BY cards.id""",
        (norm, norm),
    ).fetchall()


MIN_TYPO_NAME = 5


def find_close_cards(connection: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """Cards whose name or alias is one edit from *name*. Call only when there is no exact match."""
    norm = normalize(name)
    found = set()
    for row in connection.execute("SELECT id, norm_name AS value FROM cards UNION ALL SELECT card_id, norm_alias FROM aliases"):
        if one_edit_apart(norm, row["value"], MIN_TYPO_NAME):
            found.add(row["id"])
    return [card_by_id(connection, card_id) for card_id in sorted(found)]


def card_by_id(connection: sqlite3.Connection, card_id: int) -> Optional[sqlite3.Row]:
    return connection.execute("SELECT * FROM cards WHERE id=?", (card_id,)).fetchone()


def count_cards(connection: sqlite3.Connection) -> int:
    return connection.execute("SELECT count(*) FROM cards").fetchone()[0]


def add_card(change: db.Change, name: str, source: str, kind: str = "person") -> int:
    card_id = change.insert("cards", kind=kind, name=name, norm_name=normalize(name), created_at=db.now(), source=source)
    words = name.split()
    if kind == "person" and len(words) > 1:
        add_alias(change, card_id, words[0], automatic=True)
    return card_id


def add_alias(change: db.Change, card_id: int, alias: str, automatic: bool = False) -> None:
    norm = normalize(alias)
    exists = change.connection.execute("SELECT 1 FROM aliases WHERE card_id=? AND norm_alias=?", (card_id, norm)).fetchone()
    if not exists:
        change.insert("aliases", card_id=card_id, alias=alias, norm_alias=norm, automatic=int(automatic), created_at=db.now())


def active_lines(connection: sqlite3.Connection, card_id: int, include_private: bool = True) -> list[sqlite3.Row]:
    """A card's current lines. Line numbers shown to the user are positions in this list."""
    rows = connection.execute(
        "SELECT * FROM details WHERE card_id=? AND closed_at IS NULL ORDER BY saved_at, id", (card_id,)
    ).fetchall()
    return [row for row in rows if include_private or not row["private"]]


def private_count(connection: sqlite3.Connection, card_id: int) -> int:
    return connection.execute("SELECT count(*) FROM details WHERE card_id=? AND closed_at IS NULL AND private=1", (card_id,)).fetchone()[0]


def all_lines(connection: sqlite3.Connection, card_id: int, include_private: bool = True) -> list[sqlite3.Row]:
    rows = connection.execute("SELECT * FROM details WHERE card_id=? ORDER BY saved_at, id", (card_id,)).fetchall()
    return [row for row in rows if include_private or not row["private"]]


def add_detail(change: db.Change, card_id: int, text: str, source: str, replaces_id: Optional[int] = None, private: bool = False) -> int:
    parsed = fields.parse_detail(text)
    return change.insert(
        "details", card_id=card_id, field=parsed.field, text=text, norm_value=parsed.norm_value,
        birth_year=parsed.birth_year, birth_month=parsed.birth_month, birth_day=parsed.birth_day,
        saved_at=db.now(), source=source, replaces_id=replaces_id, private=int(private),
    )


def correct_detail(change: db.Change, detail: sqlite3.Row, new_text: str, source: str) -> None:
    """Close the old value and add the new one. The old value is kept for history."""
    change.update("details", detail["id"], closed_at=db.now())
    add_detail(change, detail["card_id"], new_text, source, replaces_id=detail["id"], private=bool(detail["private"]))


def relation_key(relation: str) -> str:
    return normalize(relation)


def kind_for_relation(relation: str) -> str:
    return _KIND_OF.get(relation_key(relation), "person")


def add_link(change: db.Change, from_card: int, relation: str, to_card: int, source: str) -> bool:
    key = relation_key(relation)
    exists = change.connection.execute(
        "SELECT 1 FROM links WHERE from_card=? AND to_card=? AND norm_relation=? AND closed_at IS NULL", (from_card, to_card, key)
    ).fetchone()
    if exists:
        return False
    change.insert("links", from_card=from_card, relation=relation, norm_relation=key, to_card=to_card, created_at=db.now(), source=source)
    return True


def has_link(connection: sqlite3.Connection, from_card: int, relation: str, to_name: str) -> bool:
    """Whether *from_card* already has an open link of this relation to a card called *to_name*."""
    norm = normalize(to_name)
    return connection.execute(
        """SELECT 1 FROM links JOIN cards ON cards.id=links.to_card LEFT JOIN aliases ON aliases.card_id=cards.id
           WHERE links.from_card=? AND links.norm_relation=? AND links.closed_at IS NULL
           AND (cards.norm_name=? OR aliases.norm_alias=?)""",
        (from_card, relation_key(relation), norm, norm),
    ).fetchone() is not None


def link_offer_in(text: str) -> Optional[tuple[str, str]]:
    """A relation followed by a capitalized name in saved words, such as "dog's name Ollie" or
    "dog is Ollie": (relation, name). Plain text matching, no model."""
    found = _OFFER.search(text)
    if not found:
        return None
    name = _TRAILING_POSSESSIVE.sub("", found.group(2)).strip()
    return (found.group(1).casefold(), name) if name else None


def open_links(connection: sqlite3.Connection, card_id: int) -> list[sqlite3.Row]:
    """Links touching a card, in either direction, with the other card's name."""
    return connection.execute(
        """SELECT links.*, a.name AS from_name, b.name AS to_name FROM links
           JOIN cards a ON a.id=links.from_card JOIN cards b ON b.id=links.to_card
           WHERE (from_card=? OR to_card=?) AND links.closed_at IS NULL ORDER BY links.id""",
        (card_id, card_id),
    ).fetchall()


def _relation_terms(relation: str) -> set[str]:
    key = relation_key(relation)
    return _EQUIVALENT.get(key, {key})


def forward_match(relation: str, word: str) -> bool:
    terms = _relation_terms(relation)
    return word in terms or any(term in _RELATIONS["broader"].get(word, ()) for term in terms)


def reverse_match(relation: str, word: str) -> bool:
    return any(word in _RELATIONS["inverse"].get(term, ()) for term in _relation_terms(relation))
