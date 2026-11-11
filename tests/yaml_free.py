"""Small helpers to compare plugin.yaml with what register() actually registers."""

import sys
from pathlib import Path


class FakeContext:
    def __init__(self):
        self.seen = {"hooks": [], "tools": [], "commands": [], "cli": []}
        self.handlers = {}

    def register_hook(self, name, _handler):
        self.seen["hooks"].append(name)

    def register_tool(self, name, *_args, **_kwargs):
        self.seen["tools"].append(name)

    def register_command(self, name, handler=None, *_args, **_kwargs):
        self.seen["commands"].append(name)
        self.handlers[name] = handler

    def register_cli_command(self, name, *_args, **_kwargs):
        self.seen["cli"].append(name)

    def ask_choice(self, _question, _choices):
        return None

    def get_config(self, _key, default=None):
        return default

    def post_message(self, _text):
        return None


def registered():
    context = FakeContext()
    sys.modules["myfolks"].register(context)
    return context.seen


def manifest(path: Path) -> dict:
    data, key = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("  - ") and key:
            data.setdefault(key, []).append(line[4:].strip().strip('"'))
        elif line and not line.startswith(" ") and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            if value.strip():
                data[key] = value.strip().strip('"')
    return data
