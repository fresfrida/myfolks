"""Splitting and normalizing what the user typed. One place for these rules."""

from __future__ import annotations

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
