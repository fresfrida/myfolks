"""Splitting and normalizing what the user typed. One place for these rules."""

from __future__ import annotations

from typing import Optional

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
_WORD_EDGES = re.compile(r"^[^\w#+]+|[^\w]+$", re.UNICODE)


def load_data(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


STOPWORDS = frozenset(load_data("stopwords.json")["words"])


def normalize(value: str) -> str:
    """Casefolded, single-spaced form used for exact name and alias comparison."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().replace("’", "'").split())


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    end: int
    quoted: bool = False


_TOKEN = re.compile(r'"([^"]*)"|(\S+)')


_ASCII_NUMBER = re.compile(r"[0-9]{1,9}")


def ascii_number(text: str) -> Optional[int]:
    """A line, review or card number: ASCII 0-9 only, so superscripts and other scripts' digits never parse."""
    return int(text) if _ASCII_NUMBER.fullmatch(text) else None


def looks_numeric(text: str) -> bool:
    """Digits of any script, such as ² or ٣: meant as a number, but not one MyFolks accepts."""
    return any(ch.isdigit() or ch.isnumeric() for ch in text) and ascii_number(text) is None and not any(ch.isalpha() for ch in text)


def tokens(raw: str) -> list[Token]:
    """Whitespace-separated tokens; double quotes group words. Positions refer to *raw*."""
    found = []
    for match in _TOKEN.finditer(raw):
        if match.group(1) is not None:
            found.append(Token(match.group(1), match.start(), match.end(), True))
        else:
            found.append(Token(match.group(2), match.start(), match.end()))
    return found


def word(value: str) -> str:
    """One query word: casefolded, no outer punctuation, no possessive."""
    cleaned = _WORD_EDGES.sub("", normalize(value))
    return re.sub(r"'s$|'$", "", cleaned)


def query_words(raw: str) -> list[str]:
    return [w for w in (word(t.text) for t in tokens(raw)) if w]


def one_edit_apart(left: str, right: str, min_longer: int = 0) -> bool:
    """True when two different strings differ by one missing, extra or changed letter, or two swapped neighbors."""
    if left == right or max(len(left), len(right)) < min_longer or abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    start = 0
    while start < len(left) and left[start] == right[start]:
        start += 1
    if len(left) != len(right):
        return left[start:] == right[start + 1 :]
    if left[start + 1 :] == right[start + 1 :]:
        return True
    return (
        start + 1 < len(left)
        and left[start] == right[start + 1]
        and left[start + 1] == right[start]
        and left[start + 2 :] == right[start + 2 :]
    )


def changed_one_letter(left: str, right: str, min_length: int = 0) -> bool:
    """True when two same-length words differ in exactly one position, like bears and wears."""
    if len(left) != len(right) or len(left) < min_length:
        return False
    return sum(1 for a, b in zip(left, right) if a != b) == 1
