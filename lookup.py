"""Turning a typed question into one card and the words left to search for."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from . import cards, search
from .text import STOPWORDS

Pick = Callable[[list, str], sqlite3.Row]
_CARD_ID = re.compile(r"^#([0-9]{1,9})$")
_MAX_HOPS = 4
_MAX_NAME_WORDS = 3


@dataclass
class Resolved:
    card: sqlite3.Row
    words: list[str]
    start: Optional[sqlite3.Row] = None
    start_words: Optional[list[str]] = None


def answer_lines(connection: sqlite3.Connection, found: Resolved, include_private: bool) -> tuple[sqlite3.Row, search.Results]:
    """Search the card a question reached. If links led to another card that has no answer, search the
    starting card with all the words, so "priya dog allergy" still finds "is allergic to dogs" on Priya."""
    wanted = search.important_words(found.words)
    results = search.rank(cards.active_lines(connection, found.card["id"], include_private), wanted)
    if results.direct or results.related or found.start is None or found.start["id"] == found.card["id"]:
        return found.card, results
    start_results = search.rank(cards.active_lines(connection, found.start["id"], include_private), search.important_words(found.start_words or []))
    if start_results.direct or start_results.related:
        return found.start, start_results
    return found.card, results


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


def find_close_span(connection: sqlite3.Connection, words: list[str]) -> Optional[tuple[int, int, list]]:
    """Names one edit from what was typed. These never open a card: the user must choose first."""
    for start in range(len(words)):
        if words[start] in STOPWORDS:
            continue
        for end in range(min(len(words), start + _MAX_NAME_WORDS), start, -1):
            matches = cards.find_close_cards(connection, " ".join(words[start:end]))
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
    linked, left = follow_links(connection, card, remaining, pick)
    return Resolved(linked, left, card, remaining)
