"""Turning a typed question into one card and the words left to search for."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from . import cards
from .text import STOPWORDS

Pick = Callable[[list, str], sqlite3.Row]
_CARD_ID = re.compile(r"^#(\d+)$")
_MAX_HOPS = 4


@dataclass
class Resolved:
    card: sqlite3.Row
    words: list[str]


def cards_for_words(connection: sqlite3.Connection, words: list[str]) -> list:
    match = _CARD_ID.match(words[0]) if len(words) == 1 else None
    if match:
        card = cards.card_by_id(connection, int(match[1]))
        return [card] if card is not None else []
    return cards.find_cards(connection, " ".join(words))


def find_span(connection: sqlite3.Connection, words: list[str]) -> Optional[tuple[int, int, list]]:
    """The earliest, then longest, run of words naming at least one card."""
    for start in range(len(words)):
        for end in range(len(words), start, -1):
            matches = cards_for_words(connection, words[start:end])
            if matches:
                return start, end, matches
    return None


def _link_candidates(connection: sqlite3.Connection, card_id: int, word: str) -> list:
    results = {}
    for link in cards.open_links(connection, card_id):
        outgoing = link["from_card"] == card_id
        other = link["to_card"] if outgoing else link["from_card"]
        relation_hit = cards.forward_match(link["relation"], word) if outgoing else cards.reverse_match(link["relation"], word)
        named = any(row["id"] == other for row in cards.find_cards(connection, word)) if word else False
        if relation_hit or named:
            results[other] = cards.card_by_id(connection, other)
    return list(results.values())


def follow_links(connection: sqlite3.Connection, card: sqlite3.Row, words: list[str], pick: Pick) -> tuple[sqlite3.Row, list[str]]:
    words = list(words)
    for _hop in range(_MAX_HOPS):
        for index, word in enumerate(words):
            candidates = _link_candidates(connection, card["id"], word)
            if candidates:
                card = pick(candidates, card["name"])
                del words[index]
                break
        else:
            break
    return card, words


def resolve(connection: sqlite3.Connection, words: list[str], pick: Pick) -> Optional[Resolved]:
    span = find_span(connection, words)
    if span is None:
        return None
    start, end, matches = span
    card = pick(matches, " ".join(words[start:end]))
    remaining = [w for w in words[:start] if w not in STOPWORDS] + words[end:]
    card, remaining = follow_links(connection, card, remaining, pick)
    return Resolved(card, remaining)
