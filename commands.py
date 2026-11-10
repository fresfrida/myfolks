"""/contacts: every form of the command. No model call anywhere in this path."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from . import cards, db, importer, lookup, messages, owner, search
from .text import Token, normalize, query_words, tokens
from .vault import Busy, NotSetUp, Refused, Vault, VaultError

logger = logging.getLogger(__name__)

MAX_TEXT = 2000
_WARNED_SETTING = "terminal_warning_shown"
_SELF_WORDS = {"me", "my", "i", "myself"}
_ALIAS_WORDS = {"alias", "aka", "nickname"}


class NeedsChoice(Exception):
    def __init__(self, reply: str):
        super().__init__("choice needed")
        self.reply = reply


@dataclass
class Context:
    connection: sqlite3.Connection
    source_label: str
    terminal: bool
    pick: Callable


def _hint(connection: sqlite3.Connection, card: sqlite3.Row) -> str:
    lines = cards.active_lines(connection, card["id"])
    return lines[0]["text"][:40] if lines else ""


def _picker(connection: sqlite3.Connection, ask: Optional[Callable]) -> Callable:
    def pick(matches: list, _context: str) -> sqlite3.Row:
        if len(matches) == 1:
            return matches[0]
        options = [(card["id"], card["name"], _hint(connection, card)) for card in matches]
        answer = None
        if ask is not None:
            answer = ask(
                messages.CHOOSE_QUESTION,
                [{"value": str(card_id), "label": f"{name} (#{card_id})", "description": hint} for card_id, name, hint in options],
            )
        for card in matches:
            if answer == str(card["id"]):
                return card
        raise NeedsChoice(messages.choose_fallback(options))

    return pick


def _is_pair_request(raw: str) -> Optional[str]:
    parts = tokens(raw)
    if len(parts) == 2 and parts[0].text.casefold() == "pair":
        return parts[1].text
    return None


def _messaging_owner(vault: Vault, platform: str, source) -> bool:
    """True only for the owner's private chat. Any doubt is a no."""
    if not owner.is_private_sender(source):
        return False
    if owner.sole_allowed_user(platform) == str(source.user_id):
        return True
    try:
        with vault.read() as connection:
            return owner.is_paired_owner(connection, platform, str(source.user_id))
    except VaultError:
        return False


def _pair(vault: Vault, platform: str, source, code: str) -> str:
    if not owner.is_private_sender(source):
        return messages.REFUSED
    try:
        with vault.write() as connection:
            paired = owner.try_pair(connection, platform, str(source.user_id), code)
    except VaultError:
        return messages.REFUSED
    return messages.PAIRED if paired else messages.REFUSED


def handle(raw_args: str, *, platform: Optional[str] = None, source=None, ask: Optional[Callable] = None, vault: Optional[Vault] = None) -> str:
    raw = raw_args or ""
    store = vault or Vault()
    label = owner.local_surface(platform)
    try:
        if label is None:
            if not platform:
                return messages.REFUSED
            code = _is_pair_request(raw)
            if code is not None:
                return _pair(store, platform.strip().lower(), source, code)
            if not _messaging_owner(store, platform.strip().lower(), source):
                return messages.REFUSED
            label = owner.messaging_label(platform)
        return _dispatch(raw, store, label, label == "terminal", ask)
    except NeedsChoice as choice:
        return choice.reply
    except NotSetUp:
        return messages.NOT_SET_UP
    except Refused:
        return messages.LOCKED
    except Busy:
        return messages.BUSY
    except Exception as exc:
        logger.error("MyFolks command failed: %s", type(exc).__name__)
        return messages.ERROR


def _dispatch(raw: str, vault: Vault, label: str, terminal: bool, ask: Optional[Callable]) -> str:
    parts = tokens(raw)
    verb = parts[0].text.casefold() if parts and not parts[0].quoted else ""
    writers = {"save": _save, "link": _link, "correct": _correct, "undo": _undo, "review": _review}
    if verb in writers:
        with vault.write() as connection:
            return writers[verb](Context(connection, label, terminal, _picker(connection, ask)), raw, parts[1:])
    with vault.read() as connection:
        context = Context(connection, label, terminal, _picker(connection, ask))
        if not parts:
            return messages.overview(cards.count_cards(connection))
        if verb == "history":
            return _history(context, raw, parts[1:])
        return _query(context, raw)


def _match_prefix(context: Context, parts: list[Token], limit: int) -> tuple[int, list]:
    """Longest run of leading tokens that names a card: (tokens used, matches)."""
    for used in range(min(limit, len(parts)), 0, -1):
        matches = lookup.cards_for_words(context.connection, [" ".join(p.text for p in parts[:used])])
        if matches:
            return used, matches
    return 0, []


def _match_suffix(context: Context, parts: list[Token], limit: int) -> tuple[int, list]:
    for used in range(min(limit, len(parts)), 0, -1):
        matches = lookup.cards_for_words(context.connection, [" ".join(p.text for p in parts[-used:])])
        if matches:
            return used, matches
    return 0, []


def _save(context: Context, raw: str, parts: list[Token]) -> str:
    if len(parts) < 2:
        return messages.USAGE_SAVE
    used, matches = _match_prefix(context, parts, len(parts) - 1)
    is_new = not matches
    if is_new:
        used = 1
    text = raw[parts[used].start:].strip()
    if len(text) > MAX_TEXT:
        return messages.TOO_LONG
    change = db.Change(context.connection, "save", context.source_label)
    if is_new:
        name = parts[0].text
        card_id = cards.add_card(change, name, context.source_label)
    else:
        card = context.pick(matches, parts[0].text)
        card_id, name = card["id"], card["name"]
    cards.add_detail(change, card_id, text, context.source_label)
    change.finish(f"saved to {name}")
    reply = messages.new_card(name) if is_new else messages.saved(name)
    return _with_terminal_warning(context, reply)


def _with_terminal_warning(context: Context, reply: str) -> str:
    """The first save typed in the terminal gets a one-time heads-up."""
    if not context.terminal or db.get_setting(context.connection, _WARNED_SETTING):
        return reply
    db.set_setting(context.connection, _WARNED_SETTING, "1")
    return f"{reply}\n{messages.TERMINAL_WARNING}"


def _card_for_link(context: Context, change: db.Change, name: str, matches: list, relation: str, right_side: bool, created: list[str]) -> tuple[int, str]:
    if matches:
        card = context.pick(matches, name)
        return card["id"], card["name"]
    kind = cards.kind_for_relation(relation) if right_side else "person"
    created.append(name)
    return cards.add_card(change, name, context.source_label, kind=kind), name


def _link(context: Context, _raw: str, parts: list[Token]) -> str:
    if len(parts) < 3:
        return messages.USAGE_LINK
    left_used, left_matches = _match_prefix(context, parts, len(parts) - 2)
    is_self = not left_matches and parts[0].text.casefold() in _SELF_WORDS
    if not left_matches:
        left_used = 1
    tail = parts[left_used:]
    right_used, right_matches = _match_suffix(context, tail, len(tail) - 1)
    if not right_matches:
        right_used = 1
    relation = " ".join(p.text for p in tail[:-right_used])
    left_name = " ".join(p.text for p in parts[:left_used])
    right_name = " ".join(p.text for p in tail[-right_used:])
    change = db.Change(context.connection, "link", context.source_label)
    created: list[str] = []
    if is_self:
        target_id, target_name = _card_for_link(context, change, right_name, right_matches, "", True, created)
        cards.add_alias(change, target_id, relation)
        change.finish(f"{target_name} also answers to {relation}")
        return messages.alias_added(target_name, relation)
    if relation.casefold() in _ALIAS_WORDS:
        target_id, target_name = _card_for_link(context, change, left_name, left_matches, "", False, created)
        cards.add_alias(change, target_id, right_name)
        change.finish(f"{target_name} also answers to {right_name}")
        return messages.alias_added(target_name, right_name)
    if normalize(relation).endswith(" of"):
        relation = relation[:-3].rstrip()
        left_name, right_name, left_matches, right_matches = right_name, left_name, right_matches, left_matches
    left_id, left_shown = _card_for_link(context, change, left_name, left_matches, relation, False, created)
    right_id, right_shown = _card_for_link(context, change, right_name, right_matches, relation, True, created)
    if not cards.add_link(change, left_id, relation, right_id, context.source_label):
        return messages.ALREADY_LINKED
    change.finish(f"linked {left_shown}, {relation}, {right_shown}")
    return messages.linked(left_shown, relation, right_shown, created)


def _correct(context: Context, raw: str, parts: list[Token]) -> str:
    position = next((i for i, part in enumerate(parts) if i and re.fullmatch(r"\d+", part.text)), None)
    if position is None or position + 1 >= len(parts):
        return messages.USAGE_CORRECT
    matches = lookup.cards_for_words(context.connection, [" ".join(p.text for p in parts[:position])])
    if not matches:
        return messages.NOTHING
    text = raw[parts[position + 1].start:].strip()
    if len(text) > MAX_TEXT:
        return messages.TOO_LONG
    card = context.pick(matches, parts[0].text)
    lines = cards.active_lines(context.connection, card["id"])
    number = int(parts[position].text)
    if not 1 <= number <= len(lines):
        return messages.NO_SUCH_LINE
    change = db.Change(context.connection, "correct", context.source_label)
    cards.correct_detail(change, lines[number - 1], text, context.source_label)
    change.finish(f"corrected a line on {card['name']}")
    return messages.saved(card["name"])


def _review_list(context: Context) -> str:
    rows = importer.pending_reviews(context.connection)
    if not rows:
        return messages.REVIEW_EMPTY
    entries = []
    for row in rows[:10]:
        contact, candidates = importer.review_contact(row)
        names = [(card_id, cards.card_by_id(context.connection, card_id)["name"]) for card_id in candidates]
        entries.append(messages.review_entry(row["id"], contact.name, contact.lines()[:2], names))
    return "\n".join([messages.review_title(len(rows)), *entries, messages.REVIEW_HOW])


def _review(context: Context, _raw: str, parts: list[Token]) -> str:
    if not parts:
        return _review_list(context)
    action = parts[0].text.casefold()
    if action not in ("merge", "keep") or len(parts) < 2 or not parts[1].text.isdigit():
        return messages.REVIEW_HOW
    row = context.connection.execute("SELECT * FROM review WHERE id=? AND status='pending'", (int(parts[1].text),)).fetchone()
    if row is None:
        return messages.REVIEW_NOT_FOUND
    card_id = None
    if action == "merge":
        _contact, candidates = importer.review_contact(row)
        if len(parts) >= 3 and parts[2].text.lstrip("#").isdigit():
            card_id = int(parts[2].text.lstrip("#"))
        elif len(candidates) == 1:
            card_id = candidates[0]
        if card_id not in candidates:
            return messages.REVIEW_WHICH_CARD
    return messages.done(importer.resolve_review(context.connection, row, action, card_id, context.source_label))


def _undo(context: Context, _raw: str, _parts: list[Token]) -> str:
    summary = db.undo_latest(context.connection)
    return messages.undone(summary) if summary else messages.NOTHING_TO_UNDO


def _history(context: Context, _raw: str, parts: list[Token]) -> str:
    if not parts:
        return messages.USAGE_HISTORY
    matches = lookup.cards_for_words(context.connection, [" ".join(p.text for p in parts)])
    if not matches:
        return messages.NOTHING
    card = context.pick(matches, parts[0].text)
    lines = cards.all_lines(context.connection, card["id"])
    body = [messages.history_line(l["text"], l["saved_at"], l["source"], l["closed_at"]) for l in lines]
    return "\n".join([messages.history_title(card["name"]), *(body or [messages.NO_LINES])])


def _card_view(context: Context, card: sqlite3.Row) -> str:
    lines = cards.active_lines(context.connection, card["id"])
    out = [card["name"]]
    out += [messages.card_line(i, l["text"], l["saved_at"], l["source"]) for i, l in enumerate(lines, 1)]
    if not lines:
        out.append(messages.NO_LINES)
    for link in cards.open_links(context.connection, card["id"]):
        outgoing = link["from_card"] == card["id"]
        out.append(messages.link_line(link["relation"], link["to_name"] if outgoing else link["from_name"], outgoing))
    return "\n".join(out)


def _format_results(card: sqlite3.Row, results: search.Results) -> str:
    def answer(line) -> str:
        return messages.answer_line(card["name"], line["text"], line["saved_at"], line["source"])

    if results.direct:
        return "\n".join(answer(line) for line in results.direct)
    if results.related:
        return "\n".join([messages.RELATED, *(answer(line) for line in results.related)])
    return messages.NOTHING


def _query(context: Context, raw: str) -> str:
    words = query_words(raw)
    resolved = lookup.resolve(context.connection, words, context.pick) if words else None
    if resolved is None:
        return messages.NOTHING
    wanted = search.important_words(resolved.words)
    if not wanted:
        return _card_view(context, resolved.card)
    return _format_results(resolved.card, search.rank(cards.active_lines(context.connection, resolved.card["id"]), wanted))
