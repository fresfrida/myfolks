"""Import contacts from vCard and CSV. Imported text is stored as data and never interpreted."""

from __future__ import annotations

import csv
import io
import json
import quopri
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from . import cards, db, fields
from .search import chunk_vector, cosine
from .text import normalize

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_FIELD_CHARS = 2000
SIMILAR_NAME_THRESHOLD = 0.75
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SKIPPED_PROPERTIES = {"PHOTO", "LOGO", "SOUND", "KEY"}
_MULTI_VALUE = " ::: "


class ImportFailed(Exception):
    """The file could not be read as contacts."""


@dataclass
class Incoming:
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    birthdays: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    trimmed: int = 0

    def lines(self) -> list[str]:
        return [f"phone {v}" for v in self.phones] + [f"email {v}" for v in self.emails] + [f"birthday {v}" for v in self.birthdays] + self.details


@dataclass
class Summary:
    new: int = 0
    merged: int = 0
    review: int = 0
    unchanged: int = 0
    skipped: int = 0
    trimmed: int = 0
    aliases: list = field(default_factory=list)


def _clean(value: str) -> str:
    return _CONTROL.sub("", value).strip()


def _add(target: list[str], value: str, contact: Incoming) -> None:
    cleaned = _clean(value)
    if len(cleaned) > MAX_FIELD_CHARS:
        cleaned = cleaned[:MAX_FIELD_CHARS]
        contact.trimmed += 1
    if cleaned and cleaned not in target:
        target.append(cleaned)


def decode_bytes(blob: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            if encoding == "utf-16" and not blob.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return blob.decode(encoding)
        except UnicodeDecodeError:
            continue
    return blob.decode("cp1252", errors="replace")


# ---- vCard ----------------------------------------------------------------------------------


def _is_quoted_printable(head: str) -> bool:
    return "QUOTED-PRINTABLE" in head.upper()


def _logical_lines(text: str) -> Iterable[str]:
    current: Optional[str] = None
    for line in re.split(r"\r\n|\n|\r", text):
        if current is not None and line[:1] in (" ", "\t"):
            current += line[1:]
            continue
        if current is not None and ":" in current:
            head = current.split(":", 1)[0]
            if _is_quoted_printable(head) and current.endswith("="):
                current = current[:-1] + line
                continue
        if current is not None:
            yield current
        current = line
    if current is not None:
        yield current


def _split_unquoted(value: str, separator: str, limit: int = -1) -> list[str]:
    parts, buffer, quoted, splits = [], "", False, 0
    for character in value:
        if character == '"':
            quoted = not quoted
        if character == separator and not quoted and (limit < 0 or splits < limit):
            parts.append(buffer)
            buffer = ""
            splits += 1
        else:
            buffer += character
    parts.append(buffer)
    return parts


def _unescape(value: str) -> str:
    return re.sub(r"\\([nN,;\\:])", lambda m: "\n" if m[1] in "nN" else m[1], value)


def _split_structured(value: str) -> list[str]:
    return [_unescape(part) for part in re.split(r"(?<!\\);", value)]


def _decode_value(value: str, parameters: list[str]) -> str:
    upper = [p.upper() for p in parameters]
    if not any("QUOTED-PRINTABLE" in p for p in upper):
        return value
    charset = next((p.split("=", 1)[1].strip('"') for p in parameters if p.upper().startswith("CHARSET=")), "utf-8")
    raw = quopri.decodestring(value.encode("latin-1", errors="replace"))
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _apply_vcard_property(contact: Incoming, name: str, value: str) -> None:
    if name == "FN":
        contact.name = _clean(_unescape(value))
    elif name == "N" and not contact.name:
        parts = _split_structured(value) + [""] * 5
        contact.name = _clean(" ".join(p for p in (parts[3], parts[1], parts[2], parts[0], parts[4]) if p.strip()))
    elif name == "NICKNAME":
        for alias in re.split(r"(?<!\\),", value):
            _add(contact.aliases, _unescape(alias), contact)
    elif name == "TEL":
        _add(contact.phones, _unescape(value).removeprefix("tel:"), contact)
    elif name == "EMAIL":
        _add(contact.emails, _unescape(value), contact)
    elif name == "BDAY":
        _add(contact.birthdays, _unescape(value).split("T")[0], contact)
    elif name == "ORG":
        _add(contact.details, "company " + " ".join(p for p in _split_structured(value) if p.strip()), contact)
    elif name == "TITLE":
        _add(contact.details, "job title " + _unescape(value), contact)
    elif name == "ADR":
        joined = ", ".join(p.strip() for p in _split_structured(value) if p.strip())
        if joined:
            _add(contact.details, "address " + joined, contact)
    elif name == "NOTE":
        _add(contact.details, _unescape(value), contact)


def parse_vcard(text: str) -> list[Incoming]:
    contacts, current = [], None
    for logical in _logical_lines(text):
        if ":" not in logical:
            continue
        head, value = _split_unquoted(logical, ":", 1)
        pieces = _split_unquoted(head, ";")
        name = pieces[0].rsplit(".", 1)[-1].upper()
        if name == "BEGIN" and value.strip().upper() == "VCARD":
            current = Incoming()
        elif name == "END" and value.strip().upper() == "VCARD":
            if current is not None:
                contacts.append(current)
            current = None
        elif current is not None and name not in _SKIPPED_PROPERTIES:
            _apply_vcard_property(current, name, _decode_value(value, pieces[1:]))
    return contacts


# ---- CSV (Google and Outlook exports) --------------------------------------------------------


def _key(column: str) -> str:
    return re.sub(r"\s+", " ", column.strip().casefold())


def _is_label_column(key: str) -> bool:
    return key.endswith((" - label", " - type", " display name"))


def _row_name(row: dict[str, str]) -> str:
    if row.get("name"):
        return row["name"]
    parts = [row.get(k, "") for k in ("first name", "given name", "middle name", "additional name", "last name", "family name")]
    return " ".join(p for p in parts if p)


def _csv_contact(row: dict[str, str]) -> Incoming:
    contact = Incoming(name=_clean(_row_name(row)))
    if len(contact.name) > MAX_FIELD_CHARS:
        contact.name = contact.name[:MAX_FIELD_CHARS]
        contact.trimmed += 1
    if row.get("nickname"):
        _add(contact.aliases, row["nickname"], contact)
    for key, value in row.items():
        if not value or _is_label_column(key):
            continue
        values = value.split(_MULTI_VALUE)
        if ("phone" in key or "mobile" in key) and "fax" not in key:
            for item in values:
                _add(contact.phones, item, contact)
        elif "e-mail" in key or "email" in key:
            for item in values:
                _add(contact.emails, item, contact)
    if row.get("birthday"):
        _add(contact.birthdays, row["birthday"], contact)
    company = row.get("organization name") or row.get("organization 1 - name") or row.get("company")
    if company:
        _add(contact.details, "company " + company, contact)
    title = row.get("organization title") or row.get("organization 1 - title") or row.get("job title")
    if title:
        _add(contact.details, "job title " + title, contact)
    address = row.get("address 1 - formatted") or row.get("home address") or row.get("business address")
    if address:
        _add(contact.details, "address " + " ".join(address.split()), contact)
    notes = row.get("notes") or row.get("note")
    if notes:
        _add(contact.details, notes, contact)
    return contact


def parse_csv(text: str) -> list[Incoming]:
    """Fields up to the whole file's size are read, then long ones are shortened like long notes.
    Anything the csv module still refuses becomes ImportFailed with the plain message."""
    first_line = text.split("\n", 1)[0]
    delimiter = max(",;\t", key=first_line.count)
    previous = csv.field_size_limit()
    csv.field_size_limit(max(previous, MAX_FILE_BYTES))
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        columns = {_key(column) for column in reader.fieldnames or [] if column}
        recognized = {"name", "first name", "given name", "last name", "family name", "company"}
        if not columns & recognized:
            raise ImportFailed("no name columns")
        return [_csv_contact({_key(k): (v or "").strip() for k, v in row.items() if k}) for row in reader]
    except csv.Error as exc:
        raise ImportFailed("not a readable CSV file") from exc
    finally:
        csv.field_size_limit(previous)


def parse_file(path: Path) -> list[Incoming]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ImportFailed("file too large")
    text = decode_bytes(path.read_bytes())
    if "BEGIN:VCARD" in text[:4096].upper() or path.suffix.lower() in (".vcf", ".vcard"):
        contacts = parse_vcard(text)
    else:
        contacts = parse_csv(text)
    if not contacts:
        raise ImportFailed("no contacts found")
    return contacts


# ---- Applying ---------------------------------------------------------------------------------


def _name_buckets(norm_name: str) -> set[str]:
    words = norm_name.split()
    return set(words) | {w[:3] for w in words}


def similar_names(left: str, right: str) -> bool:
    if left == right:
        return True
    left_words, right_words = set(left.split()), set(right.split())
    if left_words <= right_words or right_words <= left_words:
        return True
    return cosine(chunk_vector(left), chunk_vector(right)) >= SIMILAR_NAME_THRESHOLD


class _Index:
    """Existing and just-imported cards, for matching without comparing every pair."""

    def __init__(self, connection: sqlite3.Connection):
        self.values: dict[tuple[str, str], set[int]] = {}
        self.names: dict[int, str] = {}
        self.buckets: dict[str, set[int]] = {}
        for row in connection.execute("SELECT card_id,field,norm_value FROM details WHERE closed_at IS NULL AND norm_value IS NOT NULL"):
            self.add_value(row["field"], row["norm_value"], row["card_id"])
        for row in connection.execute("SELECT id,norm_name FROM cards"):
            self.add_name(row["id"], row["norm_name"])

    def add_value(self, kind: str, value: str, card_id: int) -> None:
        self.values.setdefault((kind, value), set()).add(card_id)

    def add_name(self, card_id: int, norm_name: str) -> None:
        self.names[card_id] = norm_name
        for bucket in _name_buckets(norm_name):
            self.buckets.setdefault(bucket, set()).add(card_id)

    def by_contact_value(self, contact: Incoming) -> set[int]:
        found: set[int] = set()
        for phone in contact.phones:
            normalized = fields.normalize_phone(phone)
            if normalized:
                found |= self.values.get(("phone", normalized), set())
        for email in contact.emails:
            normalized = fields.normalize_email(email)
            if normalized:
                found |= self.values.get(("email", normalized), set())
        return found

    def similar(self, norm_name: str) -> list[int]:
        candidates: set[int] = set()
        for bucket in _name_buckets(norm_name):
            candidates |= self.buckets.get(bucket, set())
        return sorted(card_id for card_id in candidates if similar_names(norm_name, self.names[card_id]))


def _existing_texts(connection: sqlite3.Connection, card_id: int) -> set[str]:
    return {row["text"] for row in cards.active_lines(connection, card_id)}


def merge_into(change: db.Change, card_id: int, contact: Incoming, source: str, index: Optional[_Index] = None, added_names: Optional[list] = None) -> int:
    """Add what the card doesn't already have. Returns how many things were added."""
    connection = change.connection
    existing = _existing_texts(connection, card_id)
    before = len(change.ops)
    for line in contact.lines():
        if line not in existing:
            cards.add_detail(change, card_id, line, source)
            if index is not None:
                parsed = fields.parse_detail(line)
                if parsed.norm_value:
                    index.add_value(parsed.field, parsed.norm_value, card_id)
    card = cards.card_by_id(connection, card_id)
    for alias in [*contact.aliases, *([contact.name] if contact.name and normalize(contact.name) != card["norm_name"] else [])]:
        if cards.add_alias(change, card_id, alias) and added_names is not None:
            added_names.append((cards.clean_name(alias), card["name"]))
    return len(change.ops) - before


def create_from(change: db.Change, contact: Incoming, source: str, index: Optional[_Index] = None) -> int:
    card_id = cards.add_card(change, contact.name, source)
    if index is not None:
        index.add_name(card_id, normalize(contact.name))
    merge_into(change, card_id, contact, source, index)
    return card_id


def _queue_review(change: db.Change, contact: Incoming, candidates: list[int], source: str, summary: Summary) -> None:
    """Send a contact to /contacts review, unless the same one is already waiting there."""
    payload = json.dumps({"incoming": asdict(contact), "candidates": candidates}, ensure_ascii=False)
    if change.connection.execute("SELECT 1 FROM review WHERE status='pending' AND payload=?", (payload,)).fetchone():
        summary.unchanged += 1
        return
    change.insert("review", payload=payload, created_at=db.now(), source=source)
    summary.review += 1


def _same_lines_already_there(connection: sqlite3.Connection, candidates: list[int], contact: Incoming) -> bool:
    return any(set(contact.lines()) <= _existing_texts(connection, card_id) for card_id in candidates)


def _fallback_name(contact: Incoming) -> str:
    return contact.name or (contact.emails[0] if contact.emails else contact.phones[0] if contact.phones else "")


def plan(contacts: list[Incoming]) -> list[Incoming]:
    """Work done before the store is locked: names settled and cleaned."""
    for contact in contacts:
        contact.name = cards.clean_name(_fallback_name(contact))
    return contacts


def _apply_one(connection: sqlite3.Connection, change: db.Change, index: "_Index", contact: Incoming, source: str, summary: Summary) -> None:
    summary.trimmed += contact.trimmed
    if not contact.name:
        summary.skipped += 1
        return
    by_value = index.by_contact_value(contact)
    if len(by_value) == 1:
        added = merge_into(change, next(iter(by_value)), contact, source, index, summary.aliases)
        if added:
            summary.merged += 1
        else:
            summary.unchanged += 1
    elif by_value:
        _queue_review(change, contact, sorted(by_value), source, summary)
    else:
        candidates = index.similar(normalize(contact.name))
        if not candidates:
            create_from(change, contact, source, index)
            summary.new += 1
        elif _same_lines_already_there(connection, candidates, contact):
            summary.unchanged += 1
        else:
            _queue_review(change, contact, candidates, source, summary)


def apply_contacts(connection: sqlite3.Connection, contacts: list[Incoming], source: str) -> Summary:
    """Apply every contact under one lock the caller holds."""
    summary = Summary()
    change = db.Change(connection, "import", source)
    index = _Index(connection)
    for contact in plan(contacts):
        _apply_one(connection, change, index, contact, source, summary)
    change.finish(f"imported from {source}")
    return summary


BATCH_SIZE = 200


@dataclass
class BatchResult:
    summary: Summary
    applied: int
    total: int
    stopped: Optional[Exception] = None


BATCH_PAUSE_SECONDS = 0.03  # longer than the store lock's 10 ms retry, so a waiting lookup gets its turn


def import_in_batches(vault, contacts: list[Incoming], source: str, batch_size: int = BATCH_SIZE, pause: float = BATCH_PAUSE_SECONDS) -> BatchResult:
    """Apply an import a batch at a time, each under its own short lock and atomic save, so other
    users of the store wait for one batch at most. One undo reverses every batch."""
    planned = plan(contacts)
    result = BatchResult(Summary(), 0, len(planned))
    change_id = None
    for start in range(0, len(planned), batch_size):
        if start:
            time.sleep(pause)
        part = planned[start:start + batch_size]
        batch = Summary()
        try:
            with vault.write() as connection:
                change = db.Change(connection, "import", source)
                index = _Index(connection)
                for contact in part:
                    _apply_one(connection, change, index, contact, source, batch)
                change_id = change.finish_into(f"imported from {source}", change_id)
                if change_id is not None and start + batch_size >= len(planned):
                    change_id = db.make_newest(connection, change_id)
        except Exception as exc:  # the batch was not saved; earlier batches stay
            result.stopped = exc
            return result
        for name in ("new", "merged", "review", "unchanged", "skipped", "trimmed"):
            setattr(result.summary, name, getattr(result.summary, name) + getattr(batch, name))
        result.summary.aliases.extend(batch.aliases)
        result.applied += len(part)
    return result


# ---- Review list ------------------------------------------------------------------------------


def pending_reviews(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    return connection.execute("SELECT * FROM review WHERE status='pending' ORDER BY id").fetchall()


def review_contact(row: sqlite3.Row) -> tuple[Incoming, list[int]]:
    payload = json.loads(row["payload"])
    return Incoming(**payload["incoming"]), payload["candidates"]


def resolve_review(connection: sqlite3.Connection, row: sqlite3.Row, action: str, card_id: Optional[int], source: str) -> str:
    contact, _candidates = review_contact(row)
    change = db.Change(connection, "review", source)
    if action == "merge":
        merge_into(change, card_id, contact, row["source"])
        name = cards.card_by_id(connection, card_id)["name"]
        status, summary = "merged", f"merged {contact.name} into {name}"
    else:
        create_from(change, contact, row["source"])
        status, summary = "kept", f"kept {contact.name} as a new card"
    change.update("review", row["id"], status=status, resolved_at=db.now())
    change.finish(summary)
    return summary
