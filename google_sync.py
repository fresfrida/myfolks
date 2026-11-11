"""Google Contacts, read-only, through the Google sign-in Hermes already keeps. Off until the owner sends
/myfolks sync. Standard library only. The sign-in is read from Hermes's folder and never written, stored,
logged or shown: errors carry only a kind. Google's text is data, imported like a contacts file."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import db, importer

logger = logging.getLogger(__name__)

SETTING = "google_sync"  # "on" or "off"; missing means off
CHECKED_SETTING = "google_sync_checked_at"  # time.time() of the last attempt, for the live check
SOURCE = "Google sync"
CHECK_EVERY_SECONDS = 600
LIVE_CHECK_SECONDS = 15.0
REQUEST_SECONDS = 10.0
TOKEN_FILE = "google_token.json"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CONNECTIONS_URL = "https://people.googleapis.com/v1/people/me/connections"
PERSON_FIELDS = "names,emailAddresses,phoneNumbers,birthdays"
PAGE_SIZE = 1000  # the People API maximum
MAX_PAGES = 200
_HOSTS = frozenset({"oauth2.googleapis.com", "people.googleapis.com"})
_CONTACT_SCOPES = frozenset({"https://www.googleapis.com/auth/contacts.readonly", "https://www.googleapis.com/auth/contacts"})
_EXPIRY_MARGIN_SECONDS = 60

NO_SIGN_IN = "no_sign_in"
NO_CONTACTS = "no_contacts"
UNREACHABLE = "unreachable"

# request(method, url, headers, body or None, timeout) -> (HTTP status, body bytes). Raises OSError when
# the network fails. Tests pass their own; nothing else ever reaches the network.
Request = Callable[[str, str, dict, Optional[bytes], float], tuple[int, bytes]]


class SyncFailed(Exception):
    """One of NO_SIGN_IN, NO_CONTACTS or UNREACHABLE. Never holds any part of the sign-in."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _https_request(method: str, url: str, headers: dict, body: Optional[bytes], timeout: float) -> tuple[int, bytes]:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in _HOSTS:
        raise ValueError("MyFolks only connects to Google's contacts and sign-in hosts over HTTPS")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (scheme and host checked above)
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def is_on(connection) -> bool:
    return db.get_setting(connection, SETTING) == "on"


def set_on(connection, on: bool) -> None:
    db.set_setting(connection, SETTING, "on" if on else "off")


def check_due(connection, now: Optional[float] = None) -> bool:
    """Sync is on and the last attempt was at least CHECK_EVERY_SECONDS ago."""
    if not is_on(connection):
        return False
    try:
        last = float(db.get_setting(connection, CHECKED_SETTING) or "-inf")
    except ValueError:
        last = float("-inf")
    return (time.time() if now is None else now) - last >= CHECK_EVERY_SECONDS


def token_path() -> Path:
    """Where Hermes's Google Workspace setup keeps its sign-in, in this profile's Hermes folder."""
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home()) / TOKEN_FILE


def _read_token(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SyncFailed(NO_SIGN_IN) from None
    if not isinstance(payload, dict) or not (payload.get("token") or payload.get("refresh_token")):
        raise SyncFailed(NO_SIGN_IN)
    raw = payload.get("scopes") or payload.get("scope")
    if raw:
        granted = set(raw.split()) if isinstance(raw, str) else {scope for scope in raw if isinstance(scope, str)} if isinstance(raw, list) else set()
        if not granted & _CONTACT_SCOPES:
            raise SyncFailed(NO_CONTACTS)
    return payload


def _still_valid(payload: dict, now: float) -> bool:
    expiry = payload.get("expiry")
    if not payload.get("token") or not isinstance(expiry, str):
        return False
    try:
        when = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)  # google-auth writes expiry in UTC without an offset
    return when.timestamp() - now > _EXPIRY_MARGIN_SECONDS


class _Clock:
    def __init__(self, seconds: Optional[float]):
        self._end = None if seconds is None else time.monotonic() + seconds

    def timeout(self) -> float:
        if self._end is None:
            return REQUEST_SECONDS
        left = self._end - time.monotonic()
        if left <= 0:
            raise SyncFailed(UNREACHABLE)
        return min(REQUEST_SECONDS, left)


def _call(request: Request, clock: _Clock, method: str, url: str, headers: dict, body: Optional[bytes] = None) -> tuple[int, bytes]:
    try:
        return request(method, url, headers, body, clock.timeout())
    except SyncFailed:
        raise
    except (OSError, ValueError):  # network down, timeout, TLS failure, or a host MyFolks never calls
        raise SyncFailed(UNREACHABLE) from None


def _refresh(payload: dict, request: Request, clock: _Clock) -> str:
    """A fresh access token, kept in memory only. The token file is never written."""
    fields = {name: payload.get(name) for name in ("client_id", "client_secret", "refresh_token")}
    if not fields["refresh_token"] or not fields["client_id"]:
        raise SyncFailed(NO_SIGN_IN)
    form = {key: value for key, value in fields.items() if value}
    form["grant_type"] = "refresh_token"
    status, body = _call(request, clock, "POST", TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, urllib.parse.urlencode(form).encode())
    if status == 200:
        try:
            token = json.loads(body).get("access_token")
        except (ValueError, AttributeError):
            token = None
        if isinstance(token, str) and token:
            return token
        raise SyncFailed(UNREACHABLE)
    if status in (400, 401) and b"invalid_grant" in body:
        raise SyncFailed(NO_SIGN_IN)  # the sign-in was revoked or expired: Hermes has to sign in again
    raise SyncFailed(UNREACHABLE)


def _people_page(access: str, page_token: Optional[str], request: Request, clock: _Clock) -> tuple[int, bytes]:
    query = {"personFields": PERSON_FIELDS, "pageSize": str(PAGE_SIZE)}
    if page_token:
        query["pageToken"] = page_token
    return _call(request, clock, "GET", f"{CONNECTIONS_URL}?{urllib.parse.urlencode(query)}", {"Authorization": f"Bearer {access}", "Accept": "application/json"})


def fetch_people(payload: dict, request: Request, clock: _Clock, now: float) -> list[dict]:
    refreshed = not _still_valid(payload, now)
    access = _refresh(payload, request, clock) if refreshed else payload["token"]
    people: list[dict] = []
    page_token = None
    for _page in range(MAX_PAGES):
        status, body = _people_page(access, page_token, request, clock)
        if status == 401 and not refreshed:
            refreshed, access = True, _refresh(payload, request, clock)
            status, body = _people_page(access, page_token, request, clock)
        if status == 401:
            raise SyncFailed(NO_SIGN_IN)
        if status == 403 and b"SCOPE_INSUFFICIENT" in body:
            raise SyncFailed(NO_CONTACTS)
        if status != 200:
            raise SyncFailed(UNREACHABLE)
        try:
            data = json.loads(body)
        except ValueError:
            raise SyncFailed(UNREACHABLE) from None
        if not isinstance(data, dict):
            raise SyncFailed(UNREACHABLE)
        people.extend(person for person in data.get("connections") or [] if isinstance(person, dict))
        page_token = data.get("nextPageToken")
        if not page_token:
            return people
    raise SyncFailed(UNREACHABLE)  # more pages than any real address book: stop rather than loop


def _primary(items) -> Optional[dict]:
    items = [item for item in items or [] if isinstance(item, dict)]
    for item in items:
        if (item.get("metadata") or {}).get("primary"):
            return item
    return items[0] if items else None


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _birthday(item: dict) -> str:
    date = item.get("date")
    if isinstance(date, dict):
        year, month, day = (date.get(key) or 0 for key in ("year", "month", "day"))
        if isinstance(month, int) and isinstance(day, int) and month and day:
            return f"{year:04d}-{month:02d}-{day:02d}" if isinstance(year, int) and year else f"--{month:02d}-{day:02d}"
        return ""
    return _text(item.get("text"))


def to_incoming(person: dict) -> Optional[importer.Incoming]:
    """One Google person as an import contact: name, phones, emails and birthday. None when it has none."""
    if (person.get("metadata") or {}).get("deleted"):
        return None
    name = _primary(person.get("names")) or {}
    full = _text(name.get("displayName")) or " ".join(part for part in (_text(name.get("givenName")), _text(name.get("familyName"))) if part) or _text(name.get("unstructuredName"))
    contact = importer.Incoming(name=importer._clean(full)[: importer.MAX_FIELD_CHARS])
    for item in person.get("phoneNumbers") or []:
        if isinstance(item, dict):
            importer._add(contact.phones, _text(item.get("value")) or _text(item.get("canonicalForm")), contact)
    for item in person.get("emailAddresses") or []:
        if isinstance(item, dict):
            importer._add(contact.emails, _text(item.get("value")), contact)
    birthday = _primary(person.get("birthdays"))
    if birthday:
        importer._add(contact.birthdays, _birthday(birthday), contact)
    if not (contact.name or contact.phones or contact.emails):
        return None
    return contact


def sync(vault, *, request: Optional[Request] = None, seconds: Optional[float] = None, path: Optional[Path] = None, now: Optional[float] = None) -> importer.BatchResult:
    """Read every Google contact and import them. Raises SyncFailed, having changed nothing, when the
    sign-in is missing or lacks contacts, or Google can't be reached in time."""
    current = time.time() if now is None else now
    with vault.write() as connection:
        db.set_setting(connection, CHECKED_SETTING, repr(current))
    try:
        payload = _read_token(path or token_path())
        people = fetch_people(payload, request or _https_request, _Clock(seconds), current)
    except SyncFailed as failure:
        logger.warning("MyFolks Google sync failed: %s", failure.kind)
        raise
    contacts = [contact for contact in (to_incoming(person) for person in people) if contact is not None]
    return importer.import_in_batches(vault, contacts, SOURCE)
