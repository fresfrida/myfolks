"""Finding lines on one card, with no model.

Each word becomes a vector of its 3-letter chunks. A line is a direct answer only when every
important question word matches a word on the line by spelling or as a true synonym. Anything else
above the cutoff, including any match through a looser topic list, is shown as related. Below the cutoff is nothing.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .text import STOPWORDS, changed_one_letter, load_data, one_edit_apart, tokens, word

SPELLING_THRESHOLD = 0.66
TOPIC_STRENGTH = 0.8
RELATED_CUTOFF = 0.5
LAST_WORD_WEIGHT = 2
MIN_PREFIX = 4
ORDINARY_ENDINGS = frozenset({"s", "es", "ed", "d", "ing", "er", "ers", "ly"})
_MIN_LY_WORD = 5  # quick, quickly. A four-letter word plus ly is usually another word: name, namely.
MIN_TYPO_LENGTH = 5
MAX_DIRECT = 8
MAX_RELATED = 3

_SUFFIXES = ("ies", "ied", "ing", "ed", "es", "s", "ic", "y")
_MIN_STEM = 4
_MIN_PLURAL_STEM = 3
_WORD_LISTS = load_data("concepts.json")
_SYNONYM_GROUPS = [frozenset(terms) for terms in _WORD_LISTS["synonyms"].values()]
_TOPIC_GROUPS = [frozenset(terms) for terms in _WORD_LISTS["topics"].values()]


@dataclass(frozen=True)
class Results:
    direct: list
    related: list
    more: int = 0


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
    if changed_one_letter(question_word, line_word, MIN_TYPO_LENGTH):
        return False
    if one_edit_apart(question_word, line_word, MIN_TYPO_LENGTH):
        return True
    left, right = _spelling_form(question_word), _spelling_form(line_word)
    if len(left) >= MIN_PREFIX and right.startswith(left):
        return _ordinary_ending(left, right[len(left):])
    left, right = _stem(left), _stem(right)
    if left == right:
        return True
    if min(len(left), len(right)) < MIN_PREFIX:
        return False
    return cosine(chunk_vector(left), chunk_vector(right)) >= SPELLING_THRESHOLD


def _ordinary_ending(word: str, ending: str) -> bool:
    if ending == "ly":
        return len(word) >= _MIN_LY_WORD
    return ending == "" or ending in ORDINARY_ENDINGS


def _prefix_only(question_word: str, line_word: str) -> bool:
    """The line word starts with the question word but goes on past an ordinary ending: phone, phonetic."""
    left, right = _spelling_form(question_word), _spelling_form(line_word)
    return len(left) >= MIN_PREFIX and right.startswith(left) and not _ordinary_ending(left, right[len(left):])


def _shares_group(groups: list[frozenset], question_word: str, line_words_: list[str]) -> bool:
    matching = [group for group in groups if any(spelled_alike(question_word, term) for term in group)]
    return any(line_word in group for group in matching for line_word in line_words_)


def line_words(text: str) -> list[str]:
    found = [word(token.text) for token in tokens(text.replace('"', " "))]
    return [w for part in found for w in re.split(r"[-/]", part) if w and w not in STOPWORDS]


def _exact_count(wanted: list[str], words_on_line: list[str]) -> int:
    return sum(1 for w in wanted if w in words_on_line)


def _strength(question_word: str, words_on_line: list[str]) -> tuple[float, bool]:
    if any(spelled_alike(question_word, w) for w in words_on_line) or _shares_group(_SYNONYM_GROUPS, question_word, words_on_line):
        return 1.0, True
    if _shares_group(_TOPIC_GROUPS, question_word, words_on_line):
        return TOPIC_STRENGTH, False
    if any(changed_one_letter(question_word, w, MIN_TYPO_LENGTH) or _prefix_only(question_word, w) for w in words_on_line):
        return TOPIC_STRENGTH, False
    return 0.0, False


def rank(lines: list, words: list[str]) -> Results:
    wanted = important_words(words)
    direct, related = [], []
    weights = [LAST_WORD_WEIGHT if i == len(wanted) - 1 else 1 for i in range(len(wanted))]
    for line in lines:
        words_on_line = line_words(line["text"])
        strengths = [_strength(w, words_on_line) for w in wanted]
        if strengths and all(by_spelling for _value, by_spelling in strengths):
            direct.append((_exact_count(wanted, words_on_line), line))
            continue
        score = sum(weight * value for weight, (value, _s) in zip(weights, strengths)) / sum(weights)
        if score >= RELATED_CUTOFF:
            related.append((score, line))
    related.sort(key=lambda pair: pair[0], reverse=True)
    direct.sort(key=lambda pair: pair[0], reverse=True)
    more = max(0, len(direct) - MAX_DIRECT)
    return Results([line for _exact, line in direct[:MAX_DIRECT]], [line for _score, line in related[:MAX_RELATED]], more)
