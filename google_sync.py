"""Google Contacts, read-only. Off until the owner sends /myfolks sync. The sign-in is Hermes's: the
plugin declares its own Google OAuth client under oauth: in plugin.yaml, the user signs in with
hermes auth add myfolks:google, and every request goes through Hermes's credentialed_provider_request,
which attaches the token, refreshes it and sends only to people.googleapis.com. MyFolks never sees,
stores or logs the token, and never shows Hermes's error text: only a failure kind. Google's text is
data, imported like a contacts file."""

from __future__ import annotations

import json
import logging
import re
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
API_OFF = "api_off"
UNREACHABLE = "unreachable"
_SCOPE_REASON = "ACCESS_TOKEN_SCOPE_INSUFFICIENT"
_API_OFF_REASONS = frozenset({"SERVICE_DISABLED", "accessNotConfigured"})  # ErrorInfo reason; legacy errors[].reason
_SAFE_NAME = re.compile(r"[A-Za-z_]{1,64}")


class SyncFailed(Exception):
    """A failure kind (NO_SIGN_IN, NO_CONTACTS, API_OFF or UNREACHABLE) and its cause for the log. The cause
    holds only an HTTP status, Google's status and reason names, or an exception class name: never a
    message, body, header or URL, so nothing secret or personal can reach the log."""

    def __init__(self, kind: str, cause: str = ""):
        super().__init__(kind)
        self.kind = kind
        self.cause = cause


def _safe(name) -> str:
    """An enum or class name as it is, or "other" for anything else: never free text."""
    return name if isinstance(name, str) and _SAFE_NAME.fullmatch(name) else "other"


def _google_error(body: bytes) -> tuple[str, list[str]]:
    """Google's error status and reasons from an error body: error.details[].reason (ErrorInfo) and the
    older error.errors[].reason. Nothing else is read."""
    try:
        error = json.loads(body).get("error")
    except (ValueError, AttributeError):
        return "", []
    if not isinstance(error, dict):
        return "", []
    reasons = [item.get("reason") for key in ("details", "errors") for item in error.get(key) or [] if isinstance(item, dict)]
    return error.get("status") or "", [reason for reason in reasons if isinstance(reason, str)]


def _http_failure(status: int, body: bytes) -> SyncFailed:
    google_status, reasons = _google_error(body)
    shown = "/".join([_safe(google_status) if google_status else "-", *(_safe(reason) for reason in reasons[:3])])
    cause = f"status={int(status)} google={shown}"
    if status == 403 and _SCOPE_REASON in reasons:
        return SyncFailed(NO_CONTACTS, cause)
    if status == 403 and _API_OFF_REASONS.intersection(reasons):
        return SyncFailed(API_OFF, cause)
    return SyncFailed(UNREACHABLE, cause)  # 401, any other 4xx or 5xx, and a redirect, which Hermes never follows


def _error_cause(exc: BaseException) -> str:
    return f"error={_safe(type(exc).__name__)}"


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
            raise SyncFailed(UNREACHABLE, "error=OutOfTime")
        return min(REQUEST_SECONDS, left)


def _get(url: str, clock: _Clock) -> tuple[int, bytes]:
    """One GET through Hermes, which attaches the sign-in. Hermes's own errors are never passed on: they
    can name the setup, the account or the request; MyFolks keeps only the kind."""
    timeout = clock.timeout()
    try:
        from hermes_cli.plugin_provider_requests import ProviderNotSignedIn, credentialed_provider_request
    except ImportError as exc:  # not running inside Hermes, or a Hermes without plugin sign-ins
        raise SyncFailed(UNREACHABLE, _error_cause(exc)) from None
    try:
        response = credentialed_provider_request(OAUTH_ID, "GET", url, headers={"Accept": "application/json"}, timeout=timeout)
    except ProviderNotSignedIn as exc:  # never signed in, signed out, revoked, or the oauth entry changed
        raise SyncFailed(NO_SIGN_IN, _error_cause(exc)) from None
    except Exception as exc:  # network, timeout, a refusal by Hermes, a failed refresh: only the class is kept
        raise SyncFailed(UNREACHABLE, _error_cause(exc)) from None
    return response.status, response.body


def fetch_people(clock: _Clock) -> list[dict]:
    people: list[dict] = []
    page_token = None
    for _page in range(MAX_PAGES):
        query = {"personFields": PERSON_FIELDS, "pageSize": str(PAGE_SIZE)}
        if page_token:
            query["pageToken"] = page_token
        status, body = _get(f"{CONNECTIONS_URL}?{urllib.parse.urlencode(query)}", clock)
        if status != 200:
            raise _http_failure(status, body)
        try:
            data = json.loads(body)
        except ValueError:
            raise SyncFailed(UNREACHABLE, "status=200 error=NotJSON") from None
        if not isinstance(data, dict):
            raise SyncFailed(UNREACHABLE, "status=200 error=NotJSON")
        people.extend(person for person in data.get("connections") or [] if isinstance(person, dict))
        page_token = data.get("nextPageToken")
        if not page_token:
            return people
    raise SyncFailed(UNREACHABLE, "error=TooManyPages")  # more pages than any real address book: stop rather than loop


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
        logger.warning("MyFolks Google sync failed: %s %s", failure.kind, failure.cause)
        raise
    contacts = [contact for contact in (to_incoming(person) for person in people) if contact is not None]
    return importer.import_in_batches(vault, contacts, SOURCE)
