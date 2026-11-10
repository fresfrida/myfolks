"""MyFolks pre-flight hello-world. Throwaway code; proves Hermes behaviors only."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

PLUGIN_ID = "myfolks"
REPLY_MARKER = "MYFOLKS-PREFLIGHT-REPLY-K7V2"
DATA_DIR_FRAGMENT = "plugin-data/myfolks"
GUARDED_NAME = "dummy.enc"


def _data_dir() -> Path:
    from plugins.plugin_storage import plugin_data_dir

    return plugin_data_dir(PLUGIN_ID)


def _log_identity(source, session_id, platform) -> None:
    """Record who called the command, for the messaging identity gate."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "platform": str(platform) if platform is not None else None,
        "session_id": session_id,
        "has_source": source is not None,
        "user_id": getattr(source, "user_id", None),
        "chat_type": getattr(source, "chat_type", None),
    }
    with (_data_dir() / "identity.log").open("a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")


def handle_contacts(raw_args: str, source=None, session_id=None, platform=None, **_context) -> str:
    _log_identity(source, session_id, platform)
    return f"{REPLY_MARKER}: hello from MyFolks."


def _strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings_in(item)


def block_store_access(tool_name: str, args: dict, task_id: str = "", **_context):
    """Refuse any tool call whose arguments name the plugin's data folder or store file."""
    for text in _strings_in(args):
        lowered = text.lower()
        if DATA_DIR_FRAGMENT in lowered or GUARDED_NAME in lowered:
            return {"action": "block", "message": "MyFolks blocked this: the contact store is not available to AI tools."}
    return None


def register(ctx) -> None:
    ctx.register_command(
        "contacts",
        handle_contacts,
        description="Look up your contacts (pre-flight hello-world)",
        args_hint="<query>",
    )
    ctx.register_hook("pre_tool_call", block_store_access)
