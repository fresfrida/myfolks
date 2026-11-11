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
SAVE_WORDS = frozenset({"remember", "save", "keep", "note"})
REFRESH_SECONDS = 10.0
_AFTER_WORD = frozenset(" \t\n,:")


def clean_word(value) -> str:
    """The configured wake word, ready to compare. Empty turns the wake word off."""
    return str(value or "").strip().lstrip("/").strip().casefold()


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
    rest = rest.strip()
    first, _, remainder = rest.partition(" ")
    if first.rstrip(",:").casefold() in SAVE_WORDS:
        return f"/contacts save {remainder.strip()}".rstrip()
    return f"/contacts {rest}".rstrip()


def gateway_hook(settings: Settings) -> Callable:
    def pre_gateway_dispatch(event=None, **_kwargs):
        text = getattr(event, "text", None)
        if not isinstance(text, str):
            return None
        command = rewrite(text, settings.current().word)
        return {"action": "rewrite", "text": command} if command else None

    return pre_gateway_dispatch


def _text_of(message) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return " ".join(part.get("text", "") for part in message if isinstance(part, dict) and isinstance(part.get("text"), str))
    return ""


def llm_hook(settings: Settings) -> Callable:
    def pre_llm_call(user_message=None, platform: str = "", **_kwargs):
        current = settings.current()
        if current.ai_on or current.mention is None:
            return None
        if not current.mention.search(_text_of(user_message)):
            return None
        in_chat_app = bool(platform) and owner.local_surface(platform) is None
        return {"context": messages.ai_wake_note(current.word, in_chat_app)}

    return pre_llm_call
