"""The wake word in chat apps, and a note for the AI. Both hooks run on every message, so a message
that doesn't match costs only in-memory string checks: no store, no decryption, no files, no logging."""

from __future__ import annotations

import re
import time
from typing import Callable, Optional

from . import messages, owner

SETTING = "wake_word"
DEFAULT_WAKE_WORD = "myfolks"
AI_SETTING = "ai_tool"
REFRESH_SECONDS = 10.0
_AFTER_WORD = frozenset(" \t\n,:")


def clean_word(value) -> str:
    """The configured wake word, ready to compare. Empty turns the wake word off."""
    return str(value or "").strip().lstrip("/").strip().casefold()


def configured_word(read_config=None) -> str:
    """The wake word as set in this Hermes profile, for the Desktop page's guide. Read-only, from the same
    place ctx.get_config reads (plugins.entries.myfolks.settings). Only a label: the default if unreadable."""
    try:
        if read_config is None:
            from hermes_cli.config import load_config_readonly as read_config
        entry = (((read_config() or {}).get("plugins") or {}).get("entries") or {}).get("myfolks") or {}
        settings = entry.get("settings") if isinstance(entry.get("settings"), dict) else entry.get("config") or {}
        return clean_word(settings.get(SETTING, DEFAULT_WAKE_WORD))
    except Exception:
        return DEFAULT_WAKE_WORD


class Settings:
    """The wake word and AI switch, read once and refreshed at most every REFRESH_SECONDS."""

    def __init__(self, read: Callable, clock: Callable[[], float] = time.monotonic):
        self._read = read
        self._clock = clock
        self._checked = float("-inf")
        self.word = DEFAULT_WAKE_WORD
        self.ai_on = False
        self.mention = _mention_pattern(self.word)

    def current(self) -> "Settings":
        now = self._clock()
        if now - self._checked >= REFRESH_SECONDS:
            self._checked = now
            try:
                word = clean_word(self._read(SETTING, DEFAULT_WAKE_WORD))
                ai_on = bool(self._read(AI_SETTING, False))
            except Exception:
                return self
            if word != self.word:
                self.word, self.mention = word, _mention_pattern(word)
            self.ai_on = ai_on
        return self


def _mention_pattern(word: str) -> Optional[re.Pattern]:
    return re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.IGNORECASE) if word else None


def rewrite(text: str, word: str) -> Optional[str]:
    """The /contacts command for a message that starts with the wake word, or None."""
    if not word or not text:
        return None
    if text[0].isspace():
        text = text.lstrip()
    size = len(word)
    if text[:size].casefold() != word:
        return None
    rest = text[size:]
    if rest and rest[0] not in _AFTER_WORD:
        return None
    rest = rest.lstrip(" \t\n")
    if rest[:1] in (",", ":"):
        rest = rest[1:]
    return f"/contacts {rest.strip()}".rstrip()  # plain words such as "remember" are read by commands.py


COMMAND_NAMES = frozenset({"contacts", "myfolks"})


def command_args(text: str, word: str) -> Optional[str]:
    """What follows /contacts, /myfolks (also /contacts@bot) or the wake word, or None. Strings only."""
    if not text:
        return None
    if text[0] == "/" or (text[0].isspace() and text.lstrip()[:1] == "/"):
        head, _, rest = text.strip().partition(" ")
        name = head[1:].split("@", 1)[0].casefold()
        return rest.strip() if name in COMMAND_NAMES else None
    command = rewrite(text, word)
    return command[len("/contacts"):].strip() if command else None


def gateway_hook(settings: Settings, answer: Optional[Callable] = None) -> Callable:
    """Messages for MyFolks are answered here, at ingress, and then skipped, so they never reach a
    busy session, the transcript or the AI. Anything that isn't the owner's, or can't be answered
    here, goes on unchanged (the wake word as /contacts). Other messages cost one string check."""

    def pre_gateway_dispatch(event=None, gateway=None, **_kwargs):
        text = getattr(event, "text", None)
        if not isinstance(text, str):
            return None
        word = settings.current().word
        args = command_args(text, word)
        if args is None:
            return None
        command = rewrite(text, word)
        fallback = {"action": "rewrite", "text": command} if command else None
        if answer is None or gateway is None:
            return fallback
        return _answer_or(answer, event, gateway, args, fallback)

    return pre_gateway_dispatch


async def _answer_or(answer: Callable, event, gateway, args: str, fallback):
    try:
        if await answer(event, gateway, args):
            return {"action": "skip", "reason": "answered by MyFolks"}
    except Exception:
        pass
    return fallback


def _is_myfolks_command(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return False
    head = stripped.split(None, 1)[0]
    return head[1:].split("@", 1)[0].casefold() in COMMAND_NAMES


def _text_of(message) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return " ".join(part.get("text", "") for part in message if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def llm_hook(settings: Settings) -> Callable:
    def pre_llm_call(user_message=None, platform: str = "", **_kwargs):
        current = settings.current()
        in_chat_app = bool(platform) and owner.local_surface(platform) is None
        if in_chat_app and _is_myfolks_command(_text_of(user_message)):
            # A /myfolks or /contacts sent while Hermes is busy reaches the AI as plain text, because
            # Hermes doesn't let plugin commands skip its busy handling. Stop it before any model request.
            return {"action": "block", "message": messages.busy_use_wake_word(current.word)}
        if current.ai_on or current.mention is None:
            return None
        if not current.mention.search(_text_of(user_message)):
            return None
        in_chat_app = bool(platform) and owner.local_surface(platform) is None
        return {"context": messages.ai_wake_note(current.word, in_chat_app)}

    return pre_llm_call
