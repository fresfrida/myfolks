"""Structured values: phone, email and birthday. Everything else stays free text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

_LABEL = re.compile(r"^(phone|mobile|cell|tel|email|e-mail|birthday|bday|born)\b[:\s]+(.+)$", re.IGNORECASE | re.DOTALL)
_PHONE_CHARS = re.compile(r"^[+\d\s().\-/]+$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MONTHS = {name: i + 1 for i, name in enumerate(
    "january february march april may june july august september october november december".split())}
_MONTHS.update({name[:3]: number for name, number in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_EARLIEST_REAL_YEAR = 1800  # exports write placeholder years such as 1604 when the year is unknown


@dataclass(frozen=True)
class Parsed:
    field: Optional[str] = None
    norm_value: Optional[str] = None
    birth_year: Optional[int] = None
    birth_month: Optional[int] = None
    birth_day: Optional[int] = None


def normalize_phone(value: str) -> Optional[str]:
    if not _PHONE_CHARS.match(value.strip()):
        return None
    digits = re.sub(r"\D", "", value)
    if not 7 <= len(digits) <= 15:
        return None
    if value.strip().startswith("+"):
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    return digits


def normalize_email(value: str) -> Optional[str]:
    candidate = value.strip().casefold()
    return candidate if _EMAIL.match(candidate) else None


def _valid(month: int, day: int) -> bool:
    days = {2: 29, 4: 30, 6: 30, 9: 30, 11: 30}.get(month, 31)
    return 1 <= month <= 12 and 1 <= day <= days


def parse_birthday(value: str) -> Optional[tuple[Optional[int], int, int]]:
    """(year or None, month, day), only when the date is unambiguous."""
    text = value.strip().casefold().rstrip(".")
    match = re.fullmatch(r"(\d{4})-?(\d{2})-?(\d{2})", text)
    if match:
        year, month, day = int(match[1]), int(match[2]), int(match[3])
        return (year if year >= _EARLIEST_REAL_YEAR else None, month, day) if _valid(month, day) else None
    match = re.fullmatch(r"--(\d{2})-?(\d{2})", text)
    if match:
        month, day = int(match[1]), int(match[2])
        return (None, month, day) if _valid(month, day) else None
    match = re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", text)
    if match and match[1] in _MONTHS:
        month, day = _MONTHS[match[1]], int(match[2])
        return (int(match[3]) if match[3] else None, month, day) if _valid(month, day) else None
    match = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?(?:,?\s+(\d{4}))?", text)
    if match and match[2] in _MONTHS:
        month, day = _MONTHS[match[2]], int(match[1])
        return (int(match[3]) if match[3] else None, month, day) if _valid(month, day) else None
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text)
    if match:
        first, second, year = int(match[1]), int(match[2]), int(match[3])
        if first > 12 and _valid(second, first):
            return (year, second, first)
        if second > 12 and _valid(first, second):
            return (year, first, second)
    return None


def parse_value(field: str, value: str) -> Optional[Parsed]:
    if field == "phone":
        normalized = normalize_phone(value)
        return Parsed("phone", normalized) if normalized else None
    if field == "email":
        normalized = normalize_email(value)
        return Parsed("email", normalized) if normalized else None
    birthday = parse_birthday(value)
    return Parsed("birthday", None, *birthday) if birthday else None


def parse_detail(text: str) -> Parsed:
    """Recognize `phone ...`, `email ...` and `birthday ...` lines; anything else is free text."""
    match = _LABEL.match(text.strip())
    if not match:
        return Parsed()
    label = match[1].casefold()
    field = "phone" if label in ("phone", "mobile", "cell", "tel") else "email" if label in ("email", "e-mail") else "birthday"
    return parse_value(field, match[2]) or Parsed()
