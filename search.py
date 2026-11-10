"""Finding lines on one card, with no model.

Each word becomes a vector of its 3-letter chunks. A line is a direct answer only when every
important question word matches a word on the line by spelling. Anything else above the cutoff,
including any match through the concept list, is shown as related. Below the cutoff is nothing.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .text import STOPWORDS, load_data, tokens, word

SPELLING_THRESHOLD = 0.66
CONCEPT_STRENGTH = 0.8
RELATED_CUTOFF = 0.5
LAST_WORD_WEIGHT = 2
MIN_PREFIX = 4
MAX_DIRECT = 5
MAX_RELATED = 3

_SUFFIXES = ("ies", "ied", "ing", "ed", "es", "s", "ic", "y")
_MIN_STEM = 4
_MIN_PLURAL_STEM = 3
_CONCEPT_GROUPS = [frozenset(terms) for terms in load_data("concepts.json")["groups"].values()]


@dataclass(frozen=True)
class Results:
    direct: list
    related: list


def important_words(words: list[str]) -> list[str]:
    return [w for w in words if w not in STOPWORDS]


def _spelling_form(value: str) -> str:
    if len(value) >= 6 and "our" in value:
        value = value.replace("our", "or")
    return value


def _stem(value: str) -> str:
    if value.endswith("s") and not value.endswith("ss") and len(value) - 1 >= _MIN_PLURAL_STEM and len(value) <= 4:
        return value[:-1]
    for suffix in _SUFFIXES:
        if value.endswith(suffix) and len(value) - len(suffix) >= _MIN_STEM:
            return value[: -len(suffix)]
    return value


def chunk_vector(value: str) -> Counter:
    padded = f"^{value}$"
    return Counter(padded[i : i + 3] for i in range(len(padded) - 2))


def cosine(left: Counter, right: Counter) -> float:
    shared = sum(left[key] * right[key] for key in left.keys() & right.keys())
    if not shared:
        return 0.0
    return shared / math.sqrt(sum(v * v for v in left.values()) * sum(v * v for v in right.values()))


def spelled_alike(question_word: str, line_word: str) -> bool:
    if question_word == line_word:
        return True
    if question_word.isdigit() or line_word.isdigit():
        return False
    left, right = _spelling_form(question_word), _spelling_form(line_word)
    if len(left) >= MIN_PREFIX and right.startswith(left):
        return True
    left, right = _stem(left), _stem(right)
    if left == right:
        return True
    if min(len(left), len(right)) < MIN_PREFIX:
        return False
    return cosine(chunk_vector(left), chunk_vector(right)) >= SPELLING_THRESHOLD


def _concept_groups_for(value: str) -> list[frozenset]:
    return [group for group in _CONCEPT_GROUPS if any(spelled_alike(value, term) for term in group)]


def _same_concept(question_word: str, line_words: list[str]) -> bool:
    groups = _concept_groups_for(question_word)
    return any(line_word in group for group in groups for line_word in line_words)


def line_words(text: str) -> list[str]:
    found = [word(token.text) for token in tokens(text.replace('"', " "))]
    return [w for part in found for w in re.split(r"[-/]", part) if w and w not in STOPWORDS]


def _strength(question_word: str, words_on_line: list[str]) -> tuple[float, bool]:
    if any(spelled_alike(question_word, w) for w in words_on_line):
        return 1.0, True
    if _same_concept(question_word, words_on_line):
        return CONCEPT_STRENGTH, False
    return 0.0, False


def rank(lines: list, words: list[str]) -> Results:
    wanted = important_words(words)
    direct, related = [], []
    weights = [LAST_WORD_WEIGHT if i == len(wanted) - 1 else 1 for i in range(len(wanted))]
    for line in lines:
        words_on_line = line_words(line["text"])
        strengths = [_strength(w, words_on_line) for w in wanted]
        if strengths and all(by_spelling for _value, by_spelling in strengths):
            direct.append(line)
            continue
        score = sum(weight * value for weight, (value, _s) in zip(weights, strengths)) / sum(weights)
        if score >= RELATED_CUTOFF:
            related.append((score, line))
    related.sort(key=lambda pair: pair[0], reverse=True)
    return Results(direct[:MAX_DIRECT], [line for _score, line in related[:MAX_RELATED]])
