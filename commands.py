"""/contacts: every form of the command. No model call anywhere in this path."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

from . import cards, db, guard, importer, lookup, messages, owner, search
from .text import STOPWORDS, Token, ascii_number, looks_numeric, normalize, one_edit_apart, query_words, tokens
from .vault import Busy, NotSetUp, Refused, Vault, VaultError

logger = logging.getLogger(__name__)

MAX_TEXT = 2000
_WARNED_SETTING = "terminal_warning_shown"
_SELF_WORDS = {"me", "my", "i", "myself"}
_ALIAS_WORDS = {"alias", "aka", "nickname"}
_TYPO_VERBS = ("save", "link", "history", "correct", "undo", "review")
_VERBS = {*_TYPO_VERBS, "hide", "unhide"}
_MAX_QUESTIONS = 4
_OFFER_KEY = "offer:link"
_BOLD_SURFACE = messages.TELEGRAM
_POSSESSIVE = re.compile(r"(?:['\u2019][sS]|['\u2019])$")
_NEW_FLAG = "--new"
_RETIRED_FLAGS = {"--private", "--computer-only"}
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
    show_private: bool = True
    is_owner: bool = True


def _hint(connection: sqlite3.Connection, card: sqlite3.Row) -> str:
    lines = cards.active_lines(connection, card["id"], include_private=False)
    return lines[0]["text"][:40] if lines else ""


def _picker(connection: sqlite3.Connection, answers: dict, is_owner: bool = True) -> Callable:
    def pick(matches: list, _context: str) -> sqlite3.Row:
        if len(matches) == 1:
            return matches[0]
        key = "pick:" + ",".join(str(card["id"]) for card in matches)
        for card in matches:
            if answers.get(key) == str(card["id"]):
                return card
        if not is_owner:  # people the owner shares with look up by name only: no card numbers, no hints
            raise NeedsAnswer(
                key,
                messages.CHOOSE_QUESTION,
                [{"value": str(card["id"]), "label": messages.choice_label(card["name"])} for card in matches],
                messages.choose_names_fallback([card["name"] for card in matches]),
            )
        options = [(card["id"], card["name"], _hint(connection, card)) for card in matches]
        raise NeedsAnswer(
            key,
            messages.CHOOSE_QUESTION,
            [{"value": str(card_id), "label": messages.choice_label(name, card_id), "description": messages.value(hint)} for card_id, name, hint in options],
            messages.choose_fallback(options),
        )

    return pick


def _is_pair_request(raw: str) -> Optional[str]:
    parts = tokens(raw)
    if len(parts) == 2 and parts[0].text.casefold() == "pair":
        return parts[1].text
    return None


def _pair(vault: Vault, platform: str, source, code: str) -> str:
    if not owner.is_private_sender(source):
        return messages.REFUSED
    try:
        with vault.write() as connection:
            paired = owner.try_pair(connection, platform, str(source.user_id), code)
    except VaultError:
        return messages.REFUSED
    return messages.PAIRED if paired else messages.REFUSED


def answers_at_ingress(raw_args: str, *, platform: str, source, shared=None, vault: Optional[Vault] = None) -> bool:
    """Whether a chat message for MyFolks can be answered before Hermes sees it: the owner, or someone
    the owner shares with, in a private chat, on a set-up store. Pairing and anyone else go on to Hermes."""
    if not platform or owner.local_surface(platform) is not None or _is_pair_request(raw_args or "") is not None:
        return False
    try:
        store = vault or Vault()
        if not store.exists():
            return False
        name = platform.strip().lower()
        if not owner.hermes_allows(name, getattr(source, "user_id", None)):
            return False  # Hermes would turn this sender away: leave it to Hermes, unchanged
        return owner.is_messaging_owner(store, name, source) or owner.shared_access(name, source, shared) is not None
    except Exception:
        return False


def handle(raw_args: str, *, platform: Optional[str] = None, source=None, ask: Optional[Callable] = None, vault: Optional[Vault] = None, shared=None) -> str:
    raw = raw_args or ""
    access = owner.FULL_ACCESS
    label = owner.local_surface(platform)
    try:
        store = vault or Vault()
        if label is None:
            if not platform:
                return messages.REFUSED
            code = _is_pair_request(raw)
            if code is not None:
                return _pair(store, platform.strip().lower(), source, code)
            name = platform.strip().lower()
            if not owner.is_messaging_owner(store, name, source):
                access = owner.shared_access(name, source, shared)
                if access is None:
                    return messages.REFUSED
            label = owner.messaging_label(platform)
        with messages.replies_for(label):
            reply = _dispatch(raw, store, label, label == "terminal", ask, access)
        if label in owner.LOCAL_SURFACES.values() and guard.take_failure_notice(store.directory):
            return f"{messages.GUARD_FAILED}\n{reply}"
        return reply
    except NotSetUp:
        return messages.NOT_SET_UP
    except Refused:
        return messages.LOCKED
    except Busy:
        return messages.BUSY
    except Exception as exc:
        logger.error("MyFolks command failed: %s", type(exc).__name__)
        return messages.ERROR


def _dispatch(raw: str, vault: Vault, label: str, terminal: bool, ask: Optional[Callable], access: str = owner.FULL_ACCESS) -> str:
    answers: dict = {}
    for _attempt in range(_MAX_QUESTIONS):
        try:
            reply = _run(raw, vault, label, terminal, answers, access)
        except NeedsAnswer as need:
            answer = ask(need.question, need.choices) if ask is not None else None
            if answer is None:
                return need.fallback
            answers[need.key] = answer
            continue
        offer = answers.get(_OFFER_KEY)
        if offer is None or not _allowed_for(access, "link"):
            return reply
        return _offer_link(reply, offer, vault, label, terminal, ask, access)
    return messages.ERROR


def _offer_link(reply: str, offer: tuple[str, str, str], vault: Vault, label: str, terminal: bool, ask: Optional[Callable], access: str) -> str:
    """After a save that names someone's dog, mom and so on: ask to link them, outside the lock."""
    left, relation, right = offer
    command = f"link {_display_token(left)} {relation} {_display_token(right)}"
    choices = [{"value": "link", "label": messages.LINK_CHOICE}, {"value": "not-now", "label": messages.NOT_NOW_CHOICE}]
    answer = ask(messages.link_offer(right, left, relation), choices) if ask is not None else None
    if answer is None:
        return f"{reply}\n{messages.link_offer_command('/contacts ' + command)}"
    if answer != "link":
        return reply
    return f"{reply}\n{_dispatch(command, vault, label, terminal, ask, access)}"


def _context(connection: sqlite3.Connection, label: str, terminal: bool, answers: dict, access: str = owner.FULL_ACCESS) -> Context:
    show_private = label in owner.LOCAL_SURFACES.values()
    is_owner = access == owner.FULL_ACCESS
    return Context(connection, label, terminal, _picker(connection, answers, is_owner), answers, show_private, is_owner)


def _closest_verb(word: str) -> Optional[str]:
    close = [verb for verb in _TYPO_VERBS if one_edit_apart(word, verb)]
    return close[0] if len(close) == 1 else None


def _lookup_finds_something(context: Context, raw: str) -> bool:
    """Whether the whole line, read as a plain question, reaches a card and an answer."""
    words = query_words(raw)
    span = lookup.find_span(context.connection, words) if words else None
    if span is None:
        return False
    if len(span[2]) > 1:
        return True
    remaining = search.important_words(words[: span[0]] + words[span[1] :])
    card, remaining = lookup.follow_links(context.connection, span[2][0], remaining, context.pick)
    if not remaining:
        return True
    results = search.rank(cards.active_lines(context.connection, card["id"], context.show_private), remaining)
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


def _allowed_for(access: str, verb: str) -> bool:
    """People the owner shared with may look things up; "add" may also save."""
    if access == owner.FULL_ACCESS:
        return True
    if verb == "save":
        return access == "add"
    return verb not in _VERBS


def _run(raw: str, vault: Vault, label: str, terminal: bool, answers: dict, access: str) -> str:
    parts = tokens(raw)
    if access != owner.FULL_ACCESS and any(part.text.startswith("#") and len(part.text) > 1 for part in parts):
        return messages.NOTHING  # only the owner opens cards by number; sharing is lookup by name, never browsing
    verb = _verb_for(vault, raw, parts, label, terminal, answers)
    if not _allowed_for(access, verb):
        return messages.REFUSED
    writers = {"save": _save, "link": _link, "correct": _correct, "undo": _undo, "review": _review, "hide": _hide, "unhide": _unhide}
    if verb in writers:
        try:
            with vault.write() as connection:
                return writers[verb](_context(connection, label, terminal, answers, access), raw, parts[1:])
        except db.UndoBlocked as blocked:  # raised inside the write, so the store is not saved
            return messages.undo_blocked(blocked.summary)
    with vault.read() as connection:
        context = _context(connection, label, terminal, answers, access)
        if not parts:
            return messages.overview(cards.count_cards(connection), db.get_setting(connection, "set_up_at"), db.get_setting(connection, "set_up_from"))
        if verb == "history":
            return _history(context, raw, parts[1:])
        return _query(context, raw)


def _span_names(parts: list[Token], possessive: bool = False) -> list[str]:
    """Names a run of tokens can mean, exact first. With *possessive*, Mel's or James' also means
    Mel or James, unless the last word was quoted."""
    text = " ".join(p.text for p in parts)
    if not possessive or not parts or parts[-1].quoted:
        return [text]
    base = _POSSESSIVE.sub("", parts[-1].text)
    if not base or base == parts[-1].text:
        return [text]
    return [text, " ".join([*(p.text for p in parts[:-1]), base])]


def _name_for(parts: list[Token], possessive: bool = False) -> str:
    """The name a new card gets from these tokens: Mel's makes Mel. Always one line."""
    return cards.clean_name(_span_names(parts, possessive)[-1])


def _match_prefix(context: Context, parts: list[Token], limit: int, possessive: bool = False) -> tuple[int, list]:
    """Longest run of leading tokens that names a card: (tokens used, matches)."""
    for used in range(min(limit, len(parts)), 0, -1):
        for name in _span_names(parts[:used], possessive):
            matches = lookup.cards_for_words(context.connection, [name])
            if matches:
                return used, matches
    return 0, []


def _match_suffix(context: Context, parts: list[Token], limit: int, possessive: bool = False) -> tuple[int, list]:
    for used in range(min(limit, len(parts)), 0, -1):
        for name in _span_names(parts[-used:], possessive):
            matches = lookup.cards_for_words(context.connection, [name])
            if matches:
                return used, matches
    return 0, []


def _strip_flags(parts: list[Token]) -> tuple[list[Token], set[str]]:
    flags: set[str] = set()
    while parts and parts[0].text.casefold() == _NEW_FLAG:
        flags.add(parts[0].text.casefold())
        parts = parts[1:]
    return parts, flags


def _display_token(name: str) -> str:
    return f'"{name}"' if " " in name else name


def _close_prefix(context: Context, parts: list[Token], limit: int, possessive: bool = False) -> tuple[int, list]:
    for used in range(min(limit, _MAX_NAME_TOKENS, len(parts)), 0, -1):
        for name in _span_names(parts[:used], possessive):
            matches = cards.find_close_cards(context.connection, name)
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
    question = messages.did_you_mean([card["name"] for card in close])
    choices = [{"value": str(card["id"]), "label": messages.choice_label(card["name"])} for card in close]
    choices.append({"value": "new", "label": messages.new_card_choice(typed)})
    commands = [command_for(_display_token(card["name"])) for card in close] + [new_command]
    raise NeedsAnswer(key, question, choices, messages.did_you_mean_fallback(question, commands))


def _save(context: Context, raw: str, parts: list[Token]) -> str:
    if any(not part.quoted and part.text.casefold() in _RETIRED_FLAGS for part in parts):
        return messages.HIDE_ON_COMPUTER
    parts, flags = _strip_flags(parts)
    force_new = _NEW_FLAG in flags
    if len(parts) < 2:
        return messages.USAGE_SAVE
    used, matches = _match_prefix(context, parts, len(parts) - 1, possessive=True)
    card = None
    exact = bool(matches)
    if matches:
        card = context.pick(matches, parts[0].text)
    elif not force_new:
        close_used, close = _close_prefix(context, parts, len(parts) - 1, possessive=True)
        if close:
            typed = _name_for(parts[:close_used], possessive=True)
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
        name = _name_for(parts[:used], possessive=True)
        if not name:
            return messages.USAGE_SAVE
        card_id = cards.add_card(change, name, context.source_label)
    else:
        card_id, name = card["id"], card["name"]
    cards.add_detail(change, card_id, text, context.source_label)
    change.finish(f"saved to {name}")
    reply = messages.new_card(name) if is_new else messages.saved(name)
    linked = None
    if exact and not is_new and _allowed_link(context):
        linked = cards.link_if_certain(context.connection, cards.card_by_id(context.connection, card_id), text, context.source_label)
    if linked:
        reply = f"{reply}\n{messages.auto_linked(linked[0], name, linked[1])}"
    else:
        offer = cards.link_offer_in(text)
        if offer and normalize(offer[1]) != normalize(name) and not cards.has_link(context.connection, card_id, *offer):
            context.answers[_OFFER_KEY] = (name, offer[0], offer[1])
    return _with_terminal_warning(context, reply)


def _allowed_link(context: Context) -> bool:
    return context.is_owner


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
    parts, flags = _strip_flags(parts)
    force_new = _NEW_FLAG in flags
    if len(parts) < 3:
        return messages.USAGE_LINK
    left_used, left_matches = _match_prefix(context, parts, len(parts) - 2, possessive=True)
    is_self = not left_matches and parts[0].text.casefold() in _SELF_WORDS
    if not left_matches:
        left_used = 1
    tail = parts[left_used:]
    right_used, right_matches = _match_suffix(context, tail, len(tail) - 1, possessive=True)
    if not right_matches:
        right_used = 1
    relation = " ".join(p.text for p in tail[:-right_used])
    left_name = _name_for(parts[:left_used], possessive=True)
    right_name = _name_for(tail[-right_used:], possessive=True)
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


def _confirm_or_cancel(context: Context, typed: str, close: list, command_for: Callable[[str], str], fallback: Callable[[str, list[str]], str]) -> Optional[sqlite3.Row]:
    """Ask which close card was meant. Returns the chosen card, or None if cancelled. Names only: no details."""
    key = f"choose:{normalize(typed)}"
    answer = context.answers.get(key)
    if answer == "cancel":
        return None
    for card in close:
        if answer == str(card["id"]):
            return card
    question = messages.did_you_mean([card["name"] for card in close])
    choices = [{"value": str(card["id"]), "label": messages.choice_label(card["name"])} for card in close]
    choices.append({"value": "cancel", "label": messages.CANCEL_CHOICE})
    raise NeedsAnswer(key, question, choices, fallback(question, [command_for(_display_token(card["name"])) for card in close]))


def _hide(context: Context, _raw: str, parts: list[Token]) -> str:
    return _set_hidden(context, parts, True)


def _unhide(context: Context, _raw: str, parts: list[Token]) -> str:
    return _set_hidden(context, parts, False)


def _set_hidden(context: Context, parts: list[Token], hidden: bool) -> str:
    """Terminal and Desktop only. In chat nothing is saved."""
    if not context.show_private:
        return messages.HIDE_ON_COMPUTER
    if not parts:
        return messages.USAGE_HIDE
    verb = "hide" if hidden else "unhide"
    if len(parts) > 1 and looks_numeric(parts[-1].text):
        return messages.USAGE_HIDE
    number = ascii_number(parts[-1].text) if len(parts) > 1 else None
    name_parts = parts[:-1] if number is not None else parts
    typed = " ".join(p.text for p in name_parts)
    matches = lookup.cards_for_words(context.connection, [typed])
    if matches:
        card = context.pick(matches, typed)
    else:
        close = cards.find_close_cards(context.connection, typed)
        if not close:
            return messages.NOTHING
        suffix = f" {number}" if number is not None else ""
        card = _confirm_or_cancel(context, typed, close, lambda name: f"/contacts {verb} {name}{suffix}", messages.did_you_mean_open)
        if card is None:
            return messages.CANCELLED
    lines = cards.active_lines(context.connection, card["id"])
    if number is None:
        listed = [messages.hide_list_line(i, line["text"], bool(line["private"])) for i, line in enumerate(lines, 1)]
        return "\n".join([messages.card_heading(card["name"]), *(listed or [messages.NO_LINES]), messages.USAGE_HIDE])
    if not 1 <= number <= len(lines):
        return messages.NO_SUCH_LINE
    line = lines[number - 1]
    if bool(line["private"]) == hidden:
        return messages.ALREADY_HIDDEN if hidden else messages.ALREADY_SHOWN
    change = db.Change(context.connection, "hide", context.source_label)
    change.update("details", line["id"], private=int(hidden))
    change.finish(f"{'hid' if hidden else 'unhid'} a line on {card['name']}")
    return messages.HIDDEN_DONE if hidden else messages.SHOWN_DONE


def _correct_list(context: Context, parts: list[Token]) -> str:
    """`/contacts correct <name>` alone: the numbered lines to pick from."""
    typed = " ".join(p.text for p in parts)
    if not typed:
        return messages.USAGE_CORRECT
    matches = lookup.cards_for_words(context.connection, [typed])
    if matches:
        card = context.pick(matches, parts[0].text)
    else:
        close = cards.find_close_cards(context.connection, typed)
        if not close:
            return messages.USAGE_CORRECT
        card = _confirm_or_cancel(context, typed, close, lambda name: f"/contacts correct {name}", messages.did_you_mean_open)
        if card is None:
            return messages.CANCELLED
    lines = cards.active_lines(context.connection, card["id"], context.show_private)
    if not lines:
        return messages.NO_LINES
    render = _plain_render(context)
    numbered = [messages.numbered_line(number, render(line["text"])) for number, line in enumerate(lines, 1)]
    return "\n".join([messages.card_heading(card["name"]), *numbered, messages.USAGE_CORRECT])


def _correct(context: Context, raw: str, parts: list[Token]) -> str:
    if any(i and looks_numeric(part.text) for i, part in enumerate(parts[:3])):
        return messages.USAGE_CORRECT
    if _match_prefix(context, parts, len(parts))[0] == len(parts):
        return _correct_list(context, parts)  # the whole thing is a name, such as "Studio 54"
    used, _named = _match_prefix(context, parts, len(parts) - 2)
    if used and ascii_number(parts[used].text) is not None:
        position = used  # the longest card name first, as save does: "Studio 54 1 new text"
    else:
        position = next((i for i, part in enumerate(parts) if i and ascii_number(part.text) is not None), None)
    if position is None:
        return _correct_list(context, parts)
    if position + 1 >= len(parts):
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
        rest = f"{parts[position].text} {text}"
        card = _confirm_or_cancel(context, typed, close, lambda name: f"/contacts correct {name} {rest}", messages.did_you_mean_fallback)
        if card is None:
            return messages.CANCELLED
    lines = cards.active_lines(context.connection, card["id"], context.show_private)
    number = ascii_number(parts[position].text)
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
    item = ascii_number(parts[1].text) if len(parts) >= 2 else None
    if action not in ("merge", "keep") or item is None:
        return messages.REVIEW_HOW
    row = context.connection.execute("SELECT * FROM review WHERE id=? AND status='pending'", (item,)).fetchone()
    if row is None:
        return messages.REVIEW_NOT_FOUND
    card_id = None
    if action == "merge":
        _contact, candidates = importer.review_contact(row)
        if len(parts) >= 3:
            card_id = ascii_number(parts[2].text.lstrip("#"))
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
    if matches:
        card = context.pick(matches, parts[0].text)
    else:
        close = cards.find_close_cards(context.connection, typed)
        if not close:
            return messages.NOTHING
        card = _confirm_or_cancel(context, typed, close, lambda name: f"/contacts history {name}", messages.did_you_mean_open)
        if card is None:
            return messages.CANCELLED
    lines = cards.all_lines(context.connection, card["id"], context.show_private)
    render = _plain_render(context)
    body = [messages.history_line(l["text"], l["saved_at"], l["source"], l["closed_at"], render) for l in lines]
    return "\n".join([messages.history_title(card["name"]), *(body or [messages.NO_LINES])])


def _hidden_count(context: Context, card: sqlite3.Row) -> int:
    """How many notes to admit exist here. Only the owner, in chat, is ever told."""
    if context.show_private or not context.is_owner:
        return 0
    return cards.private_count(context.connection, card["id"])


def _plain_render(context: Context) -> Callable[[str], str]:
    return messages.telegram_plain if context.source_label == _BOLD_SURFACE else str


def _card_view(context: Context, card: sqlite3.Row) -> str:
    lines = cards.active_lines(context.connection, card["id"], context.show_private)
    render = _plain_render(context)
    out = [messages.card_heading(card["name"]), *(render(line["text"]) + (messages.HIDDEN_SUFFIX if context.terminal and line["private"] else "") for line in lines)]
    for link in cards.open_links(context.connection, card["id"]):
        outgoing = link["from_card"] == card["id"]
        out.append(messages.link_line(link["relation"], link["to_name"] if outgoing else link["from_name"], outgoing))
    hidden = _hidden_count(context, card)
    if lines:
        out.append(messages.notes_line(len(lines), max(line["saved_at"] for line in lines)))
    elif not hidden:
        out.append(messages.NO_LINES)
    if hidden:
        out.append(messages.hidden_count_line(hidden))
    return "\n".join(out)


def _format_results(context: Context, card: sqlite3.Row, results: search.Results) -> str:
    render = messages.telegram_words if context.source_label == _BOLD_SURFACE else str
    chosen = results.direct or results.related
    if not chosen:
        return messages.NOTHING
    lines = [(line["text"], line["saved_at"], line["source"]) for line in chosen]
    return messages.answer(card["name"], lines, unsure=not results.direct, render=render, more=results.more if results.direct else 0)


def _chosen_close_card(context: Context, words: list[str]) -> Optional[tuple[sqlite3.Row, list[str]]]:
    """No exact name was found: ask about close names. Returns (card, remaining words) once one is chosen."""
    span = lookup.find_close_span(context.connection, words)
    if span is None:
        return None
    start, end, close = span
    remaining = [w for w in words[:start] if w not in STOPWORDS] + words[end:]
    suffix = "".join(f" {w}" for w in remaining)
    card = _confirm_or_cancel(context, " ".join(words[start:end]), close, lambda name: f"/contacts {name}{suffix}", messages.did_you_mean_open)
    return (card, remaining) if card is not None else (None, [])


def _unknown_name(raw: str) -> str:
    """The name someone asked about, when it's clear: the only word, or a word marked with 's
    ("Tom's birthday"). Otherwise empty, and the reply stays "Nothing saved about that." """
    words = [part for part in tokens(raw) if part.text.casefold() not in STOPWORDS and not part.text.startswith("#")]
    marked = [part for part in words if not part.quoted and _POSSESSIVE.search(part.text)]
    if len(marked) == 1:
        return _POSSESSIVE.sub("", marked[0].text)
    return words[0].text if len(words) == 1 and not marked else ""


def _query(context: Context, raw: str) -> str:
    if any(part.text.startswith("#") and looks_numeric(part.text[1:]) for part in tokens(raw)):
        return messages.NOTHING  # card numbers are ASCII 0-9 only, before any text folding
    words = query_words(raw)
    if not words:
        return messages.NOTHING
    resolved = lookup.resolve(context.connection, words, context.pick)
    if resolved is None:
        chosen = _chosen_close_card(context, words)
        if chosen is None:
            typed = _unknown_name(raw)
            return messages.no_one_called(typed) if typed else messages.NOTHING
        if chosen[0] is None:
            return messages.CANCELLED
        linked, left = lookup.follow_links(context.connection, chosen[0], chosen[1], context.pick)
        resolved = lookup.Resolved(linked, left, chosen[0], chosen[1])
    if not search.important_words(resolved.words):
        return _card_view(context, resolved.card)
    card, results = lookup.answer_lines(context.connection, resolved, context.show_private)
    if not (results.direct or results.related) and _hidden_count(context, card):
        return messages.hidden_only(card["name"])
    return _format_results(context, card, results)
