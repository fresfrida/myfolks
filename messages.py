"""Every word MyFolks says to the user."""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Callable, Iterator, Optional


def _display_date(iso_timestamp: str) -> str:
    moment = datetime.fromisoformat(iso_timestamp).astimezone()
    return f"{moment:%b} {moment.day}, {moment.year}"


def receipt(iso_timestamp: str, source: str) -> str:
    return f"Saved {_display_date(iso_timestamp)} from {source}"


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_SEPARATOR = " · "
_NOT_SURE = "not sure"
# Hermes turns replies into Telegram formatting. Saved words holding any of these could be changed by that.
_TELEGRAM_FORMATTING = re.compile(r"[*_`~|\[\]#>\\$\n]")


def date_label(iso_timestamp: str, now: Optional[datetime] = None) -> str:
    """How long ago, in the user's local time."""
    saved = datetime.fromisoformat(iso_timestamp).astimezone()
    current = now or datetime.now().astimezone()
    if saved.date() >= current.date():
        return "today"
    if saved.year == current.year:
        return f"{_MONTHS[saved.month - 1]} this year"
    if saved.year == current.year - 1:
        return "last year"
    return "more than a year ago"


def _telegram_code(text: str) -> str:
    if "`" not in text and "\n" not in text:
        return f"`{text}`"
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def telegram_words(text: str) -> str:
    """Bold saved words on Telegram. Words with formatting characters go in a code span instead, so they show exactly."""
    return _telegram_code(text) if _TELEGRAM_FORMATTING.search(text) else f"**{text}**"


TELEGRAM = "Telegram"
_VALUE_RENDER: ContextVar[Callable[[str], str]] = ContextVar("myfolks_value_render", default=str)


def value(text) -> str:
    """The one place a stored or typed value enters a reply: names, relations, aliases, sources,
    summaries and commands. On Telegram it gets the same protection as saved words."""
    return _VALUE_RENDER.get()(str(text))


@contextmanager
def replies_for(surface_label: str) -> Iterator[None]:
    """Render every value in replies made inside this block for *surface_label*."""
    token = _VALUE_RENDER.set(telegram_plain if surface_label == TELEGRAM else str)
    try:
        yield
    finally:
        _VALUE_RENDER.reset(token)


def card_heading(name: str) -> str:
    return value(name)


def telegram_plain(text: str) -> str:
    """Saved words on Telegram without bold, still shown exactly."""
    return _telegram_code(text) if _TELEGRAM_FORMATTING.search(text) else text


def _with_tail(rendered: str, tail: str) -> str:
    return f"{rendered}\n{tail}" if rendered.endswith("```") else f"{rendered}{_SEPARATOR}{tail}"


def more_line(count: int, name: str) -> str:
    return f"+{count} more · /contacts {value(name)}"


def answer(name: str, lines: list[tuple[str, str, str]], unsure: bool, render: Callable[[str], str], now: Optional[datetime] = None, more: int = 0) -> str:
    """An answer readable at a glance. *lines* are (saved words, saved at, source)."""
    shown = value(name)
    head = _with_tail(shown, _NOT_SURE) if unsure else shown
    dates = [date_label(saved_at, now) for _text, saved_at, _source in lines]
    sources = {source for _text, _saved, source in lines}
    if len(set(dates)) == 1:
        tail = f"{dates[0]}{_SEPARATOR}{value(sources.pop())}" if len(sources) == 1 else dates[0]
        body = [head, *(render(line[0]) for line in lines), tail]
    else:
        body = [head, *(_with_tail(render(line[0]), date) for line, date in zip(lines, dates))]
    if more:
        body.append(more_line(more, name))
    return "\n".join(body)


NOTHING = "Nothing saved about that."


def no_one_called(name: str) -> str:
    return f"No one called {value(name)} yet."
REFUSED = "MyFolks isn't available here."
TERMINAL_WARNING = "Heads up: Hermes keeps a plain-text history of what you type in this terminal, including this command."


def saved(name: str) -> str:
    return f"Saved to {value(name)}."


def new_card(name: str) -> str:
    return f"New card for {value(name)}. Saved."


NOT_SET_UP = "Run hermes myfolks setup in your own terminal."
LOCKED = "MyFolks can't open its data. Nothing was changed. To unlock it with your recovery code, run: hermes myfolks recover"
BUSY = "MyFolks is busy. Try again in a moment."
SETUP_DONE = "MyFolks is ready."
SETUP_STORED_HERE = "MyFolks keeps what you save only in your Hermes folder, on the computer that runs Hermes. If you use it from a chat app like Telegram, that app also keeps a copy of the chat. Your address book is separate, and MyFolks never changes it."
SETUP_CODE_INTRO = "Your recovery code. It is shown once. Keep it somewhere safe:"
SETUP_CODE_PURPOSE = "You need it if MyFolks stops opening, and to back up or export."
SETUP_BACKUP_INTRO = "Back up what you've saved, in case you lose that computer:"
SETUP_BACKUP_COMMAND = "hermes myfolks backup"
SETUP_BACKUP_RESULT = "You'll get one file, locked with a passphrase you choose. Keep it somewhere else, like a USB drive."
SETUP_HERMES_BACKUP_HEADING = "About Hermes's own backups"
SETUP_HERMES_BACKUP_NOTE = "If you also run hermes backup, those files include MyFolks."
SETUP_ALREADY = "MyFolks is already set up."
SETUP_NEEDS_TERMINAL = "Run this directly in your own terminal, so the recovery code is not captured."
RECOVER_PROMPT = "Recovery code: "
RECOVER_DONE = "Recovered. MyFolks opens on this computer again."
RECOVER_REFUSED = "That code doesn't open MyFolks. Nothing was changed."
CHOOSE_QUESTION = "Which one do you mean?"
USAGE_SAVE = "To save: /contacts save <name> <text>"
USAGE_LINK = "To link: /contacts link <name> <relation> <name>"
USAGE_HISTORY = "To see history: /contacts history <name>"
USAGE_CORRECT = "To correct: /contacts correct <name> <line number> <new text>"
TOO_LONG = "That's too long to save. Keep it under 2,000 characters."
NO_SUCH_LINE = "That line number isn't on the card."
NOTHING_TO_UNDO = "Nothing to undo."
ALREADY_LINKED = "Already linked."
ERROR = "Something went wrong. Nothing was changed."
NO_LINES = "No lines saved yet."
REVIEW_EMPTY = "Nothing to review."
REVIEW_HOW = "Use /contacts review merge <number> [card number] or /contacts review keep <number>."
REVIEW_NOT_FOUND = "That item isn't on the review list."
REVIEW_WHICH_CARD = "Which card? Add its number, like /contacts review merge 3 #12."
IMPORT_FAILED = "That file couldn't be imported. Nothing was changed."
GUARD_FAILED = "Heads up: MyFolks's check on AI tool calls hit an error. Until it works again, it only blocks AI tool calls that name MyFolks or its data folder."
AI_BLOCKED = "MyFolks blocked this: the contact store is not available to AI tools."
PAIRED = "Linked. This chat is now yours."
PAIR_CODE_INTRO = "Send this in a private chat with your Hermes bot within 10 minutes:"


def setup_note(at: Optional[str], surface: Optional[str]) -> str:
    return f"Set up {date_label(at)} from {value(surface)}." if at and surface else ""


def overview(count: int, set_up_at: Optional[str] = None, set_up_from: Optional[str] = None) -> str:
    if not count:
        return EMPTY_OVERVIEW
    noun = "card" if count == 1 else "cards"
    note = setup_note(set_up_at, set_up_from)
    return (
        f"MyFolks: {count} {noun}.\n"
        + (note + "\n" if note else "")
        + "/contacts <name or question>\n"
        "/contacts save <name> <text>\n"
        "/contacts link <name> <relation> <name>\n"
        "/contacts history <name>\n"
        "/contacts correct <name> <line number> <new text>\n"
        "Undo your last change: /myfolks undo"
    )


def choose_fallback(options: list[tuple[int, str, str]]) -> str:
    lines = [f"#{card_id} {value(name)}" + (f" ({value(hint)})" if hint else "") for card_id, name, hint in options]
    return "More than one match. Use the number, like /contacts #" + str(options[0][0]) + ":\n" + "\n".join(lines)


def choose_names_fallback(names: list[str]) -> str:
    return "More than one contact has that name: " + ", ".join(value(name) for name in names) + "."


def linked(left: str, relation: str, right: str, new_names: list[str]) -> str:
    created = "".join(f"\nNew card for {value(name)}." for name in new_names)
    return f"Linked: {value(left)}, {value(relation)}, {value(right)}.{created}"


def alias_added(name: str, alias: str) -> str:
    return f"{value(name)} also answers to {value(alias)}."


def undone(summary: str) -> str:
    return f"Undone: {value(summary)}."


def undo_blocked(summary: str) -> str:
    return f"Can't undo {value(summary)}: something saved later still uses a card it made. Nothing was changed."


def link_line(relation: str, other: str, outgoing: bool) -> str:
    word = relation[:1].upper() + relation[1:]
    return f"{value(word)}: {value(other)}" if outgoing else f"{value(word)} of {value(other)}"


def notes_line(count: int, latest_saved_at: str, now: Optional[datetime] = None) -> str:
    noun = "note" if count == 1 else "notes"
    return f"{count} {noun}{_SEPARATOR}last saved {date_label(latest_saved_at, now)}"


def numbered_line(number: int, rendered: str) -> str:
    return f"{number}. {rendered}"


def history_line(text: str, iso_timestamp: str, source: str, closed_iso: str | None, render: Callable[[str], str] = str, deleted: bool = False) -> str:
    shown = render(text)
    words = f'"{shown}"' if shown == text else shown
    line = f"{words}\nSaved {_display_date(iso_timestamp)} from {value(source)}"
    if not closed_iso:
        return line
    return line + (f", deleted {_display_date(closed_iso)}" if deleted else f", replaced {_display_date(closed_iso)}")


def history_title(name: str) -> str:
    return f"{value(name)}: history"


def pair_instruction(code: str) -> str:
    return f"/contacts pair {code}"


def done(summary: str) -> str:
    return f"Done: {value(summary)}."


def review_title(count: int) -> str:
    return f"To review: {count}"


def review_entry(item: int, name: str, lines: list[str], candidates: list[tuple[int, str]]) -> str:
    matches = ", ".join(f"{value(card_name)} (#{card_id})" for card_id, card_name in candidates)
    shown = "; ".join(value(line) for line in lines)
    return f"{item}. {value(name)}" + (f" [{shown}]" if shown else "") + f" could be: {matches}"


def import_stopped(applied: int, total: int) -> str:
    return f"The import stopped after {applied} of {total} contacts. Those are saved, and /contacts undo removes them."


def import_aliases(added: list[tuple[str, str]]) -> str:
    return "Names added by merging: " + ", ".join(f"{value(alias)} (on {value(card)})" for alias, card in added) + "."


def import_summary(new: int, merged: int, review: int, unchanged: int, skipped: int, trimmed: int) -> str:
    text = f"Imported. New: {new}. Merged: {merged}. To review: {review}. Unchanged: {unchanged}. Skipped: {skipped}."
    return text + (f" Shortened to fit: {trimmed}." if trimmed else "")


# New wording below is TENTATIVE.


def did_you_mean(names) -> str:
    names = [names] if isinstance(names, str) else list(names)
    return f"Did you mean {' or '.join(value(name) for name in names)}?"


def new_card_choice(name: str) -> str:
    return f"New card for {value(name)}"


def who_is_this_for(detail_word: str) -> str:
    return f"Who is this for? Start with their name, like:\n{value(f'/myfolks save Priya {detail_word} ...')}"


def not_in_contacts(name: str) -> str:
    return f"{value(name)} isn't in your contacts yet."


def new_person_choice(name: str) -> str:
    return f"New person: {value(name)}"


def not_in_contacts_fallback(name: str, command: str) -> str:
    return f"{not_in_contacts(name)} Nothing was saved. To go ahead, send:\n{value(command)}"


def choice_label(name: str, card_id: Optional[int] = None) -> str:
    return value(name) if card_id is None else f"{value(name)} (#{card_id})"


def link_offer(right: str, left: str, relation: str) -> str:
    return f"Also link {value(right)} as {value(left)}'s {value(relation)}?"


def busy_use_wake_word(word: str) -> str:
    if not word:
        return "Wait until Hermes finishes, then send /myfolks again."
    return f"Use {word} <question> while Hermes is busy."


def ai_wake_note(word: str, in_chat_app: bool) -> str:
    start = f'"{word}" or /myfolks' if in_chat_app else "/myfolks"
    return (
        f"[MyFolks note: this message mentions {word}, but MyFolks did not run. MyFolks only answers "
        f"when a message starts with {start}. If the user wanted MyFolks, tell them that. "
        "Do not answer from guesswork about their contacts.]"
    )


def pair_ask_replace(linked: list[tuple[str, str]]) -> str:
    accounts = ", ".join(f"{platform} sender {user_id}" for platform, user_id in linked)
    return f"Already linked: {accounts}. A new code replaces that link on its platform once used. Type REPLACE to continue: "


LINK_CHOICE = "Link"
NOT_NOW_CHOICE = "Not now"


def auto_linked(right: str, left: str, relation: str) -> str:
    return f"Linked {value(right)} as {value(left)}'s {value(relation)}. Undo: /contacts undo"


BACKUP_PROMPT = "Backup passphrase: "
BACKUP_PROMPT_AGAIN = "Type it again: "
BACKUP_MISMATCH = "Those didn't match. Nothing was written."
BACKUP_SHORT = "Use at least 8 characters. Nothing was written."


def backup_done(path) -> str:
    return f"Backup saved to {path}. Keep it somewhere other than this computer. Keep the passphrase safe: without it, this file can't be opened."


BACKUP_UNWRITABLE = "MyFolks can't write a file there. Nothing was written."
FILE_EXISTS = "That file already exists. Choose a new name. Nothing was written."
RESTORE_PROMPT = "Passphrase for this backup: "
RESTORE_REFUSED = "That passphrase doesn't open this backup, or the file is damaged. Nothing was changed."
RESTORE_ASK_REPLACE = "This replaces every contact now in MyFolks. Type REPLACE to continue: "
RESTORE_CANCELLED = "Nothing was changed."
RESTORE_DONE = "Restored."
EXPORT_ASK = "This writes every contact, including notes hidden from chat, to an unencrypted file. Type EXPORT to continue: "
EXPORT_DONE = "Exported. This file is not encrypted."
TERMINAL_ONLY = "Run this directly in your own terminal."
CANCEL_CHOICE = "Cancel"
CANCELLED = "Nothing was changed."


def did_you_mean_open(question: str, commands: list[str]) -> str:
    return "\n".join([question, "To see it, send:", *(value(command) for command in commands)])


def did_you_mean_fallback(question: str, commands: list[str]) -> str:
    return "\n".join([question, "Nothing was saved. To go ahead, send one of these:", *(value(command) for command in commands)])


def ai_saved(name: str, text: str) -> str:
    shown = value(text)
    if shown == text:
        return f'MyFolks saved to {value(name)}: "{text}"'
    if shown.startswith("```"):
        return f"MyFolks saved to {value(name)}:\n{shown}"
    return f"MyFolks saved to {value(name)}: {shown}"


def hidden_only(name: str) -> str:
    return f"{value(name)}\nNothing to show here.\nSome notes are hidden from chat."


def hidden_count_line(count: int) -> str:
    return f"{count} hidden from chat"


HIDE_ON_COMPUTER = "To hide a note from chat, use your computer."
USAGE_HIDE = "To hide: /contacts hide <name> <line number>. To show again: /contacts unhide <name> <line number>."
HIDDEN_DONE = "Hidden from chat."
HIDDEN_SUFFIX = " · hidden from chat"
SHOWN_DONE = "Showing in chat again."
ALREADY_HIDDEN = "That line is already hidden from chat."
ALREADY_SHOWN = "That line is already showing in chat."


def hide_list_line(number: int, text: str, hidden: bool) -> str:
    return f"{number}. {text}" + (f"{_SEPARATOR}hidden from chat" if hidden else "")


# Google sync. New wording, TENTATIVE.
SYNC_NO_SIGN_IN = (
    "MyFolks isn't signed in to Google yet. On the computer that runs Hermes, run:\n"
    "  hermes auth add myfolks:google\n"
    "then send /myfolks sync again. Or import a contacts file instead: hermes myfolks import <file>"
)
SYNC_NO_CONTACTS = (
    "MyFolks's Google sign-in doesn't include your contacts. Run hermes auth add myfolks:google again and allow Contacts, then send /myfolks sync again.\n"
    "Or import a contacts file instead: hermes myfolks import <file>"
)
SYNC_UNREACHABLE = "Couldn't reach Google contacts. Nothing was changed. Try /myfolks sync again later."
SYNC_API_OFF = "Google's People API is off for your Google Cloud project. Turn it on: APIs & Services > Library > People API > Enable. Then send /myfolks sync again."
SYNC_OFF = "Google sync is off. MyFolks won't connect to Google. Your people stay here. Turn it back on: /myfolks sync"
SYNC_USAGE = "To sync Google contacts: /myfolks sync    To stop: /myfolks sync off"
SYNC_CHECK_FAILED = "Couldn't check Google contacts just now."
SYNC_FIRST_NOTE = "From now on, MyFolks checks Google when you mention someone new."
SYNC_STOP = "Stop syncing: /myfolks sync off"
SETUP_NEXT = "Next, bring in your contacts: send /myfolks sync to use your Google contacts, or run hermes myfolks import <file>."
EMPTY_OVERVIEW = (
    "MyFolks: no one saved yet.\n"
    "\n"
    "Bring in your contacts from Google:\n"
    "  /myfolks sync\n"
    "Or from a file, on the computer that runs Hermes:\n"
    "  hermes myfolks import <file>\n"
    "\n"
    "Or save someone now:\n"
    "  /myfolks save Priya is allergic to peanuts"
)


def sync_summary(added: int, matched: int, to_check: int) -> str:
    if not (added or matched or to_check):
        return "Google contacts synced: nothing new."
    line = f"Google contacts synced: {added} {'person' if added == 1 else 'people'} added, {matched} matched to people already here"
    return line + (f", {to_check} to check." if to_check else ".")


def sync_first(added: int, matched: int, to_check: int) -> str:
    last = f"Check the {to_check}: /myfolks review    {SYNC_STOP}" if to_check else SYNC_STOP
    return "\n".join([sync_summary(added, matched, to_check), SYNC_FIRST_NOTE, last])


# Delete. New wording, TENTATIVE.
UNDO_CHANGED_SINCE = "Can't undo that: something changed since. See History."
USAGE_DELETE = "To delete someone: /myfolks delete <name>    One line: /myfolks delete <name> <line number>"


def deleted_person(name: str) -> str:
    return f"Deleted {value(name)} from MyFolks. Undo: /myfolks undo"


def deleted_line(number: int, name: str) -> str:
    return f"Deleted line {number} from {value(name)}. Undo: /myfolks undo"


def did_you_mean_delete_fallback(question: str, commands: list[str]) -> str:
    return "\n".join([question, "Nothing was deleted. To go ahead, send one of these:", *(value(command) for command in commands)])
