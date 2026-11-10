"""pre_tool_call rule: refuse AI tool calls that directly name the store, its keys or the typed history.

This is defense in depth. An indirect route, such as a wildcard in a shell command, can get past it.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
from pathlib import Path
from typing import Iterable, Iterator, Optional

from . import messages

logger = logging.getLogger(__name__)

HISTORY_FILE = ".hermes_history"
_DATA_FRAGMENT = "plugin-data/myfolks"
_MAX_TOKENS = 500
_FILE_BODY_KEYS = {"content", "old_string", "new_string"}
_FILE_WRITE_TOOLS = {"write_file", "patch"}
_TERMINAL_ONLY_COMMANDS = re.compile(r"\bmyfolks\s+(setup|recover|pair|backup|restore|export)\b")
_SEPARATORS = re.compile(r"[=:;|&<>()`,'\"\s]+")


def protected_paths() -> tuple[Path, Path]:
    """The plugin's data folder (store, versions, device key) and this profile's typed history."""
    from hermes_constants import get_hermes_home

    from .vault import default_directory

    return default_directory().resolve(), (Path(get_hermes_home()) / HISTORY_FILE).resolve()


def _strings(args, tool_name: str, key: Optional[str] = None) -> Iterator[str]:
    if isinstance(args, str):
        if not (tool_name in _FILE_WRITE_TOOLS and key in _FILE_BODY_KEYS):
            yield args
    elif isinstance(args, dict):
        for name, value in args.items():
            yield from _strings(value, tool_name, name)
    elif isinstance(args, (list, tuple)):
        for value in args:
            yield from _strings(value, tool_name, key)


def _candidates(text: str) -> Iterator[str]:
    yield text
    try:
        words = shlex.split(text, posix=True)
    except ValueError:
        words = text.split()
    for word in words[:_MAX_TOKENS]:
        yield word
        yield from (piece for piece in _SEPARATORS.split(word) if piece and piece != word)


def _expand(candidate: str, home: str) -> str:
    expanded = candidate.replace("${HERMES_HOME}", home).replace("$HERMES_HOME", home)
    return os.path.expanduser(os.path.expandvars(expanded))


def _resolves_inside(path_text: str, workdir: str, protected: Iterable[Path]) -> bool:
    if len(path_text) > 4096 or "\n" in path_text or "\x00" in path_text:
        return False
    path = Path(path_text if os.path.isabs(path_text) else os.path.join(workdir, path_text))
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return any(resolved == root or root in resolved.parents for root in protected)


def touches_protected(tool_name: str, args: dict, protected: tuple[Path, ...], home: str, cwd: Optional[str] = None) -> bool:
    workdir = str((args or {}).get("workdir") or cwd or os.getcwd())
    literals = [str(root) for root in protected]
    for text in _strings(args, tool_name):
        lowered = text.lower()
        if _TERMINAL_ONLY_COMMANDS.search(lowered):
            return True
        if _DATA_FRAGMENT in lowered or HISTORY_FILE in lowered or any(literal in text for literal in literals):
            return True
        if any(_resolves_inside(_expand(candidate, home), workdir, protected) for candidate in _candidates(text)):
            return True
    return False


def pre_tool_call(tool_name: str, args: dict, task_id: str = "", **_context):
    try:
        from hermes_constants import get_hermes_home

        if touches_protected(tool_name, args, protected_paths(), str(get_hermes_home())):
            return {"action": "block", "message": messages.AI_BLOCKED}
    except Exception as exc:
        logger.error("MyFolks guard failed: %s", type(exc).__name__)
    return None
