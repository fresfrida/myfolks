"""What the Desktop page asks for. Every call goes through the same vault, search and review code as /contacts.

Desktop is the owner surface. Contact data only ever leaves here as a return value: nothing is logged.
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from . import cards, db, importer, lookup, messages, owner, search
from .text import normalize, query_words
from .vault import Busy, NotSetUp, Refused, Vault, VaultError

SOURCE = owner.LOCAL_SURFACES["desktop"]
MAX_LIST = 200
MAX_TEXT = 2000


class _Ambiguous(Exception):
    def __init__(self, matches: list):
        super().__init__("several matches")
        self.matches = matches


def _pick(matches: list, _context: str) -> sqlite3.Row:
    if len(matches) == 1:
        return matches[0]
    raise _Ambiguous(matches)


def state_for(error: VaultError) -> dict:
    if isinstance(error, NotSetUp):
        return {"state": "not_set_up"}
    if isinstance(error, Busy):
        return {"state": "busy"}
    if isinstance(error, Refused):
        return {"state": "locked"}
    return {"state": "error"}


def status(vault: Optional[Vault] = None) -> dict:
    with (vault or Vault()).read() as connection:
        return {
            "state": "ready",
            "cards": cards.count_cards(connection),
            "review": len(importer.pending_reviews(connection)),
        }


def _summary(card: sqlite3.Row) -> dict:
    return {"id": card["id"], "name": card["name"], "kind": card["kind"]}


def _line(line: sqlite3.Row, number: Optional[int] = None) -> dict:
    return {"id": line["id"], "number": number, "text": line["text"], "receipt": messages.receipt(line["saved_at"], line["source"]), "private": bool(line["private"])}


def _matching_cards(connection: sqlite3.Connection, query: str) -> tuple[list, int]:
    needle = normalize(query)
    rows = connection.execute(
        """SELECT DISTINCT cards.* FROM cards LEFT JOIN aliases ON aliases.card_id=cards.id
           WHERE ?='' OR instr(cards.norm_name, ?)>0 OR instr(aliases.norm_alias, ?)>0
           ORDER BY cards.norm_name, cards.id""",
        (needle, needle, needle),
    ).fetchall()
    return rows[:MAX_LIST], len(rows)


def _answer(connection: sqlite3.Connection, words: list[str]) -> Optional[dict]:
    if not words:
        return None
    try:
        resolved = lookup.resolve(connection, words, _pick)
    except _Ambiguous as ambiguous:
        return {"kind": "choose", "choices": [_summary(card) for card in ambiguous.matches]}
    if resolved is None:
        close = lookup.find_close_span(connection, words)
        if close is None:
            return {"kind": "nothing"}
        return {"kind": "did_you_mean", "question": messages.did_you_mean(" or ".join(card["name"] for card in close[2])), "choices": [_summary(card) for card in close[2]]}
    wanted = search.important_words(resolved.words)
    if not wanted:
        return {"kind": "card", "card": _summary(resolved.card)}
    found_card, results = lookup.answer_lines(connection, resolved, include_private=True)
    card = _summary(found_card)
    if results.direct:
        return {"kind": "direct", "card": card, "lines": [_line(l) for l in results.direct]}
    if results.related:
        return {"kind": "related", "card": card, "lines": [_line(l) for l in results.related]}
    return {"kind": "nothing", "card": card}


def find(query: str, vault: Optional[Vault] = None) -> dict:
    with (vault or Vault()).read() as connection:
        rows, total = _matching_cards(connection, query)
        return {
            "state": "ready",
            "cards": [_summary(card) for card in rows],
            "total": total,
            "answer": _answer(connection, query_words(query)),
        }


def card_detail(card_id: int, vault: Optional[Vault] = None) -> dict:
    with (vault or Vault()).read() as connection:
        card = cards.card_by_id(connection, card_id)
        if card is None:
            return {"state": "missing"}
        links = []
        for link in cards.open_links(connection, card_id):
            outgoing = link["from_card"] == card_id
            links.append({
                "relation": link["relation"],
                "outgoing": outgoing,
                "id": link["to_card"] if outgoing else link["from_card"],
                "name": link["to_name"] if outgoing else link["from_name"],
            })
        return {
            "state": "ready",
            "card": _summary(card),
            "lines": [_line(line, number) for number, line in enumerate(cards.active_lines(connection, card_id), 1)],
            "links": links,
        }


def save_line(card_id: int, text: str, vault: Optional[Vault] = None) -> dict:
    cleaned = (text or "").strip()
    if not cleaned or len(cleaned) > MAX_TEXT:
        return {"state": "invalid"}
    with (vault or Vault()).write() as connection:
        card = cards.card_by_id(connection, card_id)
        if card is None:
            return {"state": "missing"}
        change = db.Change(connection, "save", SOURCE)
        cards.add_detail(change, card_id, cleaned, SOURCE)
        change.finish(f"saved to {card['name']}")
        return {"state": "ready", "message": messages.saved(card["name"])}


def set_hidden(line_id: int, hidden: bool, vault: Optional[Vault] = None) -> dict:
    with (vault or Vault()).write() as connection:
        line = connection.execute("SELECT * FROM details WHERE id=? AND closed_at IS NULL", (line_id,)).fetchone()
        if line is None:
            return {"state": "missing"}
        if bool(line["private"]) != bool(hidden):
            card = cards.card_by_id(connection, line["card_id"])
            change = db.Change(connection, "hide", SOURCE)
            change.update("details", line_id, private=int(bool(hidden)))
            change.finish(f"{'hid' if hidden else 'unhid'} a line on {card['name']}")
        return {"state": "ready"}


def review_list(vault: Optional[Vault] = None) -> dict:
    with (vault or Vault()).read() as connection:
        items = []
        for row in importer.pending_reviews(connection):
            contact, candidates = importer.review_contact(row)
            items.append({
                "id": row["id"],
                "name": contact.name,
                "lines": contact.lines()[:3],
                "candidates": [_summary(cards.card_by_id(connection, card_id)) for card_id in candidates],
            })
        return {"state": "ready", "items": items}


def resolve_review(item_id: int, action: str, card_id: Optional[int], vault: Optional[Vault] = None) -> dict:
    if action not in ("merge", "keep"):
        return {"state": "invalid"}
    with (vault or Vault()).write() as connection:
        row = connection.execute("SELECT * FROM review WHERE id=? AND status='pending'", (item_id,)).fetchone()
        if row is None:
            return {"state": "missing"}
        if action == "merge":
            _contact, candidates = importer.review_contact(row)
            if card_id is None and len(candidates) == 1:
                card_id = candidates[0]
            if card_id not in candidates:
                return {"state": "invalid"}
        return {"state": "ready", "message": messages.done(importer.resolve_review(connection, row, action, card_id, SOURCE))}
