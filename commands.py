"""/contacts: every form of the command. No model call anywhere in this path."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from . import cards, db, importer, lookup, messages, owner, search
from .text import Token, normalize, one_edit_apart, query_words, tokens
from .vault import Busy, NotSetUp, Refused, Vault, VaultError

logger = logging.getLogger(__name__)

MAX_TEXT = 2000
_WARNED_SETTING = "terminal_warning_shown"
_SELF_WORDS = {"me", "my", "i", "myself"}
_ALIAS_WORDS = {"alias", "aka", "nickname"}
_TYPO_VERBS = ("save", "link", "history", "correct", "undo", "review")
_VERBS = set(_TYPO_VERBS)
_MAX_QUESTIONS = 4
_NEW_FLAG = "--new"
_MAX_NAME_TOKENS = 3


class NeedsAnswer(Exception):
    """A question for the user. Raised so it is asked after the store is unlocked."""

    def __init__(self, key: str, question: str, choices: list[dict], fallback: str):
        super().__init__("answer needed")
        self.key = key
        self.question = question
        self.choices = choices
        self.fallback = fallback


@dataclass
class Context:
    connection: sqlite3.Connection
    source_label: str
    terminal: bool
    pick: Callable
    answers: dict


def _hint(connection: sqlite3.Connection, card: sqlite3.Row) -> str:
    lines = cards.active_lines(connection, card["id"])
    return lines[0]["text"][:40] if lines else ""


def _picker(connection: sqlite3.Connection, answers: dict) -> Callable:
    def pick(matches: list, _context: str) -> sqlite3.Row:
        if len(matches) == 1:
            return matches[0]
        key = "pick:" + ",".join(str(card["id"]) for card in matches)
        for card in matches:
            if answers.get(key) == str(card["id"]):
                return card
        options = [(card["id"], card["name"], _hint(connection, card)) for card in matches]
        raise NeedsAnswer(
            key,
            messages.CHOOSE_QUESTION,
            [{"value": str(card_id), "label": f"{name} (#{card_id})", "description": hint} for card_id, name, hint in options],
            messages.choose_fallback(options),
        )

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
    label = owner.local_surface(platform)
    try:
        store = vault or Vault()
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
    answers: dict = {}
    for _attempt in range(_MAX_QUESTIONS):
        try:
            return _run(raw, vault, label, terminal, answers)
        except NeedsAnswer as need:
            answer = ask(need.question, need.choices) if ask is not None else None
            if answer is None:
                return need.fallback
            answers[need.key] = answer
    return messages.ERROR


def _context(connection: sqlite3.Connection, label: str, terminal: bool, answers: dict) -> Context:
    return Context(connection, label, terminal, _picker(connection, answers), answers)


def _closest_verb(word: str) -> Optional[str]:
    close = [verb for verb in _TYPO_VERBS if one_edit_apart(word, verb)]
    return close[0] if len(close) == 1 else None


def _lookup_finds_something(context: Context, raw: str) -> bool:
    """Whether the whole line, read as a plain question, reaches a card and an answer."""
    words = query_words(raw)
    span = (lookup.find_span(context.connection, words) or lookup.find_close_span(context.connection, words)) if words else None
    if span is None:
        return False
    if len(span[2]) > 1:
        return True
    remaining = search.important_words(words[: span[0]] + words[span[1] :])
    card, remaining = lookup.follow_links(context.connection, span[2][0], remaining, context.pick)
    if not remaining:
        return True
    results = search.rank(cards.active_lines(context.connection, card["id"]), remaining)
    return bool(results.direct or results.related)


def _verb_for(vault: Vault, raw: str, parts: list[Token], label: str, terminal: bool, answers: dict) -> str:
    if not parts or parts[0].quoted:
        return ""
    verb = parts[0].text.casefold()
    if verb in _VERBS:
        return verb
    corrected = _closest_verb(verb)
    if corrected is None:
        return verb
    with vault.read() as connection:
        return verb if _lookup_finds_something(_context(connection, label, terminal, answers), raw) else corrected


def _run(raw: str, vault: Vault, label: str, terminal: bool, answers: dict) -> str:
    parts = tokens(raw)
    verb = _verb_for(vault, raw, parts, label, terminal, answers)
    writers = {"save": _save, "link": _link, "correct": _correct, "undo": _undo, "review": _review}
    if verb in writers:
        with vault.write() as connection:
            return writers[verb](_context(connection, label, terminal, answers), raw, parts[1:])
    with vault.read() as connection:
        context = _context(connection, label, terminal, answers)
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


def _strip_new_flag(parts: list[Token]) -> tuple[list[Token], bool]:
    if parts and parts[0].text.casefold() == _NEW_FLAG:
        return parts[1:], True
    return parts, False


def _display_token(name: str) -> str:
    return f'"{name}"' if " " in name else name


def _close_prefix(context: Context, parts: list[Token], limit: int) -> tuple[int, list]:
    for used in range(min(limit, _MAX_NAME_TOKENS, len(parts)), 0, -1):
        matches = cards.find_close_cards(context.connection, " ".join(p.text for p in parts[:used]))
        if matches:
            return used, matches
    return 0, []


def _confirm_close_name(context: Context, typed: str, close: list, command_for: Callable[[str], str], new_command: str) -> Optional[sqlite3.Row]:
    """Ask whether a mistyped name means an existing card. Returns the card, or None for a new card."""
    key = f"close:{normalize(typed)}"
    answer = context.answers.get(key)
    if answer == "new":
        return None
    for card in close:
        if answer == str(card["id"]):
            return card
    question = messages.did_you_mean(close[0]["name"] if len(close) == 1 else " or ".join(card["name"] for card in close))
    choices = [{"value": str(card["id"]), "label": card["name"]} for card in close]
    choices.append({"value": "new", "label": messages.new_card_choice(typed)})
    commands = [command_for(_display_token(card["name"])) for card in close] + [new_command]
    raise NeedsAnswer(key, question, choices, messages.did_you_mean_fallback(question, commands))


def _save(context: Context, raw: str, parts: list[Token]) -> str:
    parts, force_new = _strip_new_flag(parts)
    if len(parts) < 2:
        return messages.USAGE_SAVE
    used, matches = _match_prefix(context, parts, len(parts) - 1)
    card = None
    if matches:
        card = context.pick(matches, parts[0].text)
    elif not force_new:
        close_used, close = _close_prefix(context, parts, len(parts) - 1)
        if close:
            typed = " ".join(p.text for p in parts[:close_used])
            text = raw[parts[close_used].start:].strip()
            card = _confirm_close_name(
                context, typed, close,
                lambda name: f"/contacts save {name} {text}",
                f"/contacts save {_NEW_FLAG} {_display_token(typed)} {text}",
            )
            used = close_used
    if card is None and not used:
        used = 1
    text = raw[parts[used].start:].strip()
    if len(text) > MAX_TEXT:
        return messages.TOO_LONG
    change = db.Change(context.connection, "save", context.source_label)
    is_new = card is None
    if is_new:
        name = " ".join(p.text for p in parts[:used])
        card_id = cards.add_card(change, name, context.source_label)
    else:
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


def _card_for_link(context: Context, change: db.Change, name: str, matches: list, relation: str, right_side: bool, created: list[str], confirm: Optional[Callable] = None) -> tuple[int, str]:
    if matches:
        card = context.pick(matches, name)
        return card["id"], card["name"]
    if confirm is not None:
        close = cards.find_close_cards(context.connection, name)
        if close:
            card = confirm(name, close)
            if card is not None:
                return card["id"], card["name"]
    kind = cards.kind_for_relation(relation) if right_side else "person"
    created.append(name)
    return cards.add_card(change, name, context.source_label, kind=kind), name


def _link(context: Context, _raw: str, parts: list[Token]) -> str:
    parts, force_new = _strip_new_flag(parts)
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

    def confirm_for(other_is_right: bool) -> Optional[Callable]:
        if force_new:
            return None

        def confirm(typed: str, close: list) -> Optional[sqlite3.Row]:
            def command_for(name: str) -> str:
                pair = (name, _display_token(right_name)) if other_is_right else (_display_token(left_name), name)
                return f"/contacts link {pair[0]} {relation} {pair[1]}"

            new_command = f"/contacts link {_NEW_FLAG} {_display_token(left_name)} {relation} {_display_token(right_name)}"
            return _confirm_close_name(context, typed, close, command_for, new_command)

        return confirm

    left_id, left_shown = _card_for_link(context, change, left_name, left_matches, relation, False, created, confirm_for(True))
    right_id, right_shown = _card_for_link(context, change, right_name, right_matches, relation, True, created, confirm_for(False))
    if not cards.add_link(change, left_id, relation, right_id, context.source_label):
        return messages.ALREADY_LINKED
    change.finish(f"linked {left_shown}, {relation}, {right_shown}")
    return messages.linked(left_shown, relation, right_shown, created)


def _confirm_close_for_correct(context: Context, typed: str, close: list, position_text: str) -> Optional[sqlite3.Row]:
    key = f"correct:{normalize(typed)}"
    answer = context.answers.get(key)
    if answer == "cancel":
        return None
    for card in close:
        if answer == str(card["id"]):
            return card
    question = messages.did_you_mean(close[0]["name"] if len(close) == 1 else " or ".join(card["name"] for card in close))
    choices = [{"value": str(card["id"]), "label": card["name"]} for card in close] + [{"value": "cancel", "label": messages.CANCEL_CHOICE}]
    commands = [f"/contacts correct {_display_token(card['name'])} {position_text}" for card in close]
    raise NeedsAnswer(key, question, choices, messages.did_you_mean_fallback(question, commands))


def _correct(context: Context, raw: str, parts: list[Token]) -> str:
    position = next((i for i, part in enumerate(parts) if i and re.fullmatch(r"\d+", part.text)), None)
    if position is None or position + 1 >= len(parts):
        return messages.USAGE_CORRECT
    typed = " ".join(p.text for p in parts[:position])
    text = raw[parts[position + 1].start:].strip()
    if len(text) > MAX_TEXT:
        return messages.TOO_LONG
    matches = lookup.cards_for_words(context.connection, [typed])
    if matches:
        card = context.pick(matches, parts[0].text)
    else:
        close = cards.find_close_cards(context.connection, typed)
        if not close:
            return messages.NOTHING
        card = _confirm_close_for_correct(context, typed, close, f"{parts[position].text} {text}")
        if card is None:
            return messages.CANCELLED
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
    typed = " ".join(p.text for p in parts)
    matches = lookup.cards_for_words(context.connection, [typed])
    corrected = False
    if not matches:
        matches = cards.find_close_cards(context.connection, typed)
        corrected = len(matches) == 1
    if not matches:
        return messages.NOTHING
    card = context.pick(matches, parts[0].text)
    lines = cards.all_lines(context.connection, card["id"])
    body = [messages.history_line(l["text"], l["saved_at"], l["source"], l["closed_at"]) for l in lines]
    reply = "\n".join([messages.history_title(card["name"]), *(body or [messages.NO_LINES])])
    return messages.showing(card["name"], reply) if corrected else reply


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
    if wanted:
        reply = _format_results(resolved.card, search.rank(cards.active_lines(context.connection, resolved.card["id"]), wanted))
    else:
        reply = _card_view(context, resolved.card)
    return messages.showing(resolved.card["name"], reply) if resolved.corrected else reply
