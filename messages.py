"""Every word MyFolks says to the user. All wording here is TENTATIVE until the Owner approves it."""

from __future__ import annotations

from datetime import datetime


def _display_date(iso_timestamp: str) -> str:
    moment = datetime.fromisoformat(iso_timestamp).astimezone()
    return f"{moment:%b} {moment.day}, {moment.year}"


def answer_line(name: str, saved_words: str, iso_timestamp: str, source: str) -> str:
    return f'{name}: "{saved_words}"\nSaved {_display_date(iso_timestamp)} from {source}'


RELATED = "Related, not sure:"
NOTHING = "Nothing saved about that."
REFUSED = "MyFolks isn't available here."
TERMINAL_WARNING = "Heads up: Hermes keeps a plain-text history of what you type in this terminal, including this command."


def saved(name: str) -> str:
    return f"Saved to {name}."


def new_card(name: str) -> str:
    return f"New card for {name}. Saved."


# Wording below was not in the brief; listed for the Owner's review.
NOT_SET_UP = "MyFolks isn't set up yet. Run this in your terminal: hermes myfolks setup"
LOCKED = "MyFolks can't open its data. Nothing was changed. If you moved to a new device, run: hermes myfolks recover"
BUSY = "MyFolks is busy. Try again in a moment."
SETUP_DONE = "MyFolks is ready."
SETUP_CODE_INTRO = "Your recovery code. It is shown once. Keep it somewhere safe:"
SETUP_CODE_NEEDED = "Without this code and this device, your contacts cannot be recovered."
SETUP_ALREADY = "MyFolks is already set up."
SETUP_NEEDS_TERMINAL = "Run this directly in your own terminal, so the recovery code is not captured."
RECOVER_PROMPT = "Recovery code: "
RECOVER_DONE = "Recovered. This device can open MyFolks again."
RECOVER_REFUSED = "That code doesn't open MyFolks. Nothing was changed."
