"""Google Contacts, read-only. Off until the owner sends /myfolks sync. The sign-in is Hermes's: the
plugin declares its own Google OAuth client under oauth: in plugin.yaml, the user signs in with
hermes auth add myfolks:google, and every request goes through Hermes's credentialed_provider_request,
which attaches the token, refreshes it and sends only to people.googleapis.com. MyFolks never sees,
stores or logs the token, and never shows Hermes's error text: only a failure kind. Google's text is
data, imported like a contacts file."""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from typing import Optional

from . import db, importer

logger = logging.getLogger(__name__)

SETTING = "google_sync"  # "on" or "off"; missing means off
CHECKED_SETTING = "google_sync_checked_at"  # time.time() of the last attempt, for the live check
SOURCE = "Google sync"
OAUTH_ID = "google"  # the id of the oauth: entry in plugin.yaml
CHECK_EVERY_SECONDS = 600
LIVE_CHECK_SECONDS = 15.0
REQUEST_SECONDS = 10.0
CONNECTIONS_URL = "https://people.googleapis.com/v1/people/me/connections"
PERSON_FIELDS = "names,emailAddresses,phoneNumbers,birthdays"
PAGE_SIZE = 1000  # the People API maximum
MAX_PAGES = 200

NO_SIGN_IN = "no_sign_in"
NO_CONTACTS = "no_contacts"
UNREACHABLE = "unreachable"


class SyncFailed(Exception):
    """One of NO_SIGN_IN, NO_CONTACTS or UNREACHABLE. Never holds Hermes's error text."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


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


def _get(url: str, clock: _Clock) -> tuple[int, bytes]:
    """One GET through Hermes, which attaches the sign-in. Hermes's own errors are never passed on: they
    can name the setup, the account or the request; MyFolks keeps only the kind."""
    timeout = clock.timeout()
    try:
        from hermes_cli.plugin_provider_requests import ProviderNotSignedIn, credentialed_provider_request
    except ImportError:  # not running inside Hermes, or a Hermes without plugin sign-ins
        raise SyncFailed(UNREACHABLE) from None
    try:
        response = credentialed_provider_request(OAUTH_ID, "GET", url, headers={"Accept": "application/json"}, timeout=timeout)
    except ProviderNotSignedIn:  # never signed in, signed out, revoked, or the oauth entry changed
        raise SyncFailed(NO_SIGN_IN) from None
    except Exception:  # network, timeout, a refusal by Hermes, a failed refresh: never shown, never logged
        raise SyncFailed(UNREACHABLE) from None
    return response.status, response.body


def fetch_people(clock: _Clock) -> list[dict]:
    people: list[dict] = []
    page_token = None
    for _page in range(MAX_PAGES):
        query = {"personFields": PERSON_FIELDS, "pageSize": str(PAGE_SIZE)}
        if page_token:
            query["pageToken"] = page_token
        status, body = _get(f"{CONNECTIONS_URL}?{urllib.parse.urlencode(query)}", clock)
        if status == 403 and b"ACCESS_TOKEN_SCOPE_INSUFFICIENT" in body:
            raise SyncFailed(NO_CONTACTS)
        if status != 200:  # 401, any other 4xx or 5xx, and a redirect, which Hermes never follows
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


def sync(vault, *, seconds: Optional[float] = None, now: Optional[float] = None) -> importer.BatchResult:
    """Read every Google contact and import them. Raises SyncFailed, having changed nothing, when MyFolks
    isn't signed in, the sign-in lacks contacts, or Google can't be reached in time."""
    current = time.time() if now is None else now
    with vault.write() as connection:
        db.set_setting(connection, CHECKED_SETTING, repr(current))
    try:
        people = fetch_people(_Clock(seconds))
    except SyncFailed as failure:
        logger.warning("MyFolks Google sync failed: %s", failure.kind)
        raise
    contacts = [contact for contact in (to_incoming(person) for person in people) if contact is not None]
    return importer.import_in_batches(vault, contacts, SOURCE)
