"""Every word MyFolks says to the user."""

from __future__ import annotations

from datetime import datetime


def _display_date(iso_timestamp: str) -> str:
    moment = datetime.fromisoformat(iso_timestamp).astimezone()
    return f"{moment:%b} {moment.day}, {moment.year}"


def receipt(iso_timestamp: str, source: str) -> str:
    return f"Saved {_display_date(iso_timestamp)} from {source}"


def answer_line(name: str, saved_words: str, iso_timestamp: str, source: str) -> str:
    return f'{name}: "{saved_words}"\n{receipt(iso_timestamp, source)}'


RELATED = "Related, not sure:"
NOTHING = "Nothing saved about that."
REFUSED = "MyFolks isn't available here."
TERMINAL_WARNING = "Heads up: Hermes keeps a plain-text history of what you type in this terminal, including this command."


def saved(name: str) -> str:
    return f"Saved to {name}."


def new_card(name: str) -> str:
    return f"New card for {name}. Saved."


NOT_SET_UP = "MyFolks isn't set up yet. Run this in your terminal: hermes myfolks setup"
LOCKED = "MyFolks can't open its data. Nothing was changed. If you moved to a new device, run: hermes myfolks recover"
BUSY = "MyFolks is busy. Try again in a moment."
SETUP_DONE = "MyFolks is ready."
SETUP_CODE_INTRO = "Your recovery code. It is shown once. Keep it somewhere safe:"
SETUP_CODE_NEEDED = "If you lose both this device and this code, your contacts are gone."
SETUP_ALREADY = "MyFolks is already set up."
SETUP_NEEDS_TERMINAL = "Run this directly in your own terminal, so the recovery code is not captured."
RECOVER_PROMPT = "Recovery code: "
RECOVER_DONE = "Recovered. This device can open MyFolks again."
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
AI_BLOCKED = "MyFolks blocked this: the contact store is not available to AI tools."
PAIRED = "Linked. This chat is now yours."
PAIR_CODE_INTRO = "Send this in a private chat with your Hermes bot within 10 minutes:"


def overview(count: int) -> str:
    noun = "card" if count == 1 else "cards"
    return (
        f"MyFolks: {count} {noun}.\n"
        "/contacts <name or question>\n"
        "/contacts save <name> <text>\n"
        "/contacts link <name> <relation> <name>\n"
        "/contacts history <name>\n"
        "/contacts correct <name> <line number> <new text>\n"
        "/contacts undo"
    )


def choose_fallback(options: list[tuple[int, str, str]]) -> str:
    lines = [f"#{card_id} {name}" + (f" ({hint})" if hint else "") for card_id, name, hint in options]
    return "More than one match. Use the number, like /contacts #" + str(options[0][0]) + ":\n" + "\n".join(lines)


def linked(left: str, relation: str, right: str, new_names: list[str]) -> str:
    created = "".join(f"\nNew card for {name}." for name in new_names)
    return f"Linked: {left}, {relation}, {right}.{created}"


def alias_added(name: str, alias: str) -> str:
    return f"{name} also answers to {alias}."


def undone(summary: str) -> str:
    return f"Undone: {summary}."


def card_line(number: int, text: str, iso_timestamp: str, source: str) -> str:
    return f"{number}. {text} ({_display_date(iso_timestamp)}, {source})"


def link_line(relation: str, other: str, outgoing: bool) -> str:
    return f"{relation}: {other}" if outgoing else f"{relation} of: {other}"


def history_line(text: str, iso_timestamp: str, source: str, closed_iso: str | None) -> str:
    line = f'"{text}"\nSaved {_display_date(iso_timestamp)} from {source}'
    return line + (f", replaced {_display_date(closed_iso)}" if closed_iso else "")


def history_title(name: str) -> str:
    return f"{name}: history"


def pair_instruction(code: str) -> str:
    return f"/contacts pair {code}"


def done(summary: str) -> str:
    return f"Done: {summary}."


def review_title(count: int) -> str:
    return f"To review: {count}"


def review_entry(item: int, name: str, lines: list[str], candidates: list[tuple[int, str]]) -> str:
    matches = ", ".join(f"{card_name} (#{card_id})" for card_id, card_name in candidates)
    shown = "; ".join(lines)
    return f"{item}. {name}" + (f" [{shown}]" if shown else "") + f" could be: {matches}"


def import_summary(new: int, merged: int, review: int, unchanged: int, skipped: int, trimmed: int) -> str:
    text = f"Imported. New: {new}. Merged: {merged}. To review: {review}. Unchanged: {unchanged}. Skipped: {skipped}."
    return text + (f" Shortened to fit: {trimmed}." if trimmed else "")


# New wording below is TENTATIVE.


def showing(name: str, reply: str) -> str:
    return f"Showing {name}.\n{reply}"


def did_you_mean(name: str) -> str:
    return f"Did you mean {name}?"


def new_card_choice(name: str) -> str:
    return f"New card for {name}"


CANCEL_CHOICE = "Cancel"
CANCELLED = "Nothing was changed."


def did_you_mean_fallback(question: str, commands: list[str]) -> str:
    return "\n".join([question, "Nothing was saved. To go ahead, send one of these:", *commands])


def ai_saved(name: str, text: str) -> str:
    return f'MyFolks saved to {name}: "{text}"'
