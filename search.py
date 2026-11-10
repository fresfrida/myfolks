"""Finding lines on one card. Interim exact-word version; replaced by the full search."""

from __future__ import annotations

from dataclasses import dataclass

from .text import STOPWORDS, word


@dataclass(frozen=True)
class Results:
    direct: list
    related: list


def important_words(words: list[str]) -> list[str]:
    return [w for w in words if w not in STOPWORDS]


def rank(lines: list, words: list[str]) -> Results:
    wanted = important_words(words)
    direct = [line for line in lines if all(w in {word(part) for part in line["text"].split()} for w in wanted)]
    return Results(direct, [])
