"""The first /contacts or /myfolks in a real terminal sets MyFolks up; nowhere else does."""
import json
import re
from types import SimpleNamespace

import pytest

CODE = re.compile(r"[A-Z2-7]{4}(?:-[A-Z2-7]{4}){7}")


@pytest.fixture
def fresh(tmp_path, mod):
    return mod("vault").Vault(tmp_path / "data", keys=mod("device_key").DeviceKeys(tmp_path / "data", use_keychain=False))


@pytest.fixture
def terminal():
    """First use needs no terminal check inside Hermes chat: the surface decides."""


def test_first_use_in_terminal_sets_up_and_answers(fresh, mod, terminal):
    reply = mod("commands").handle("save Priya likes tea", platform="cli", vault=fresh)
    lines = reply.split("\n")
    assert lines[:2] == ["MyFolks is ready.", "Your recovery code. It is shown once. Keep it somewhere safe:"]
    assert CODE.fullmatch(lines[2])
    assert lines[3] == "If you lose both this device and this code, your contacts are gone."
    assert lines[5].startswith("New card for Priya. Saved.")
    assert fresh.check_recovery_code(lines[2])
    second = mod("commands").handle("priya tea", platform="cli", vault=fresh)
    assert not CODE.search(second) and "likes tea" in second


def test_myfolks_command_in_the_terminal_too(fresh, mod, terminal):
    reply = mod("commands").handle("", platform="tui", vault=fresh)
    assert reply.startswith("MyFolks is ready.") and "MyFolks: 0 cards" in reply


def test_no_platform_does_not_set_up(fresh, mod):
    assert mod("commands").handle("priya", platform=None, vault=fresh) == "MyFolks isn't available here."
    assert not fresh.exists()


@pytest.mark.parametrize("platform", ["desktop", "telegram"])
def test_desktop_chat_and_messaging_point_to_the_computer(fresh, mod, terminal, monkeypatch, platform):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda _platform: ({"111"}, False))
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = mod("commands").handle("priya", platform=platform, source=source, vault=fresh)
    assert reply == "MyFolks isn't set up yet. On your computer, send /myfolks in the terminal, or open the MyFolks page in Hermes Desktop."
    assert not CODE.search(reply) and not fresh.exists()


def test_ai_tool_never_sets_up_or_sees_a_code(fresh, mod, terminal):
    reply = mod("ai_tool").handle({"action": "lookup", "question": "priya"}, vault=fresh, session=("cli", None))
    assert json.loads(reply)["status"] == "not_set_up" and not CODE.search(reply) and not fresh.exists()


def test_wake_word_on_messaging_never_sets_up(fresh, mod, terminal, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda _platform: ({"111"}, False))
    wake = mod("wake")
    command = wake.gateway_hook(wake.Settings(lambda key, default=None: default))(event=SimpleNamespace(text="myfolks remember Priya likes tea"))["text"]
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = mod("commands").handle(command[len("/contacts"):].strip(), platform="telegram", source=source, vault=fresh)
    assert not CODE.search(reply) and not fresh.exists()


def test_desktop_page_setup_shows_the_code_once(fresh, mod):
    service = mod("desktop_service")
    first = service.setup(vault=fresh)
    assert first["state"] == "ready" and CODE.fullmatch(first["code"]) and fresh.check_recovery_code(first["code"])
    assert service.setup(vault=fresh) == {"state": "ready"}


def test_hermes_myfolks_setup_still_works(fresh, mod):
    import io

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    out = Terminal()
    assert mod("cli").cmd_setup(None, vault=fresh, stdout=out) == 0
    assert CODE.search(out.getvalue())
    out = Terminal()
    assert mod("cli").cmd_setup(None, vault=fresh, stdout=out) == 1
    assert out.getvalue().strip() == "MyFolks is already set up."


def test_first_use_when_already_set_up_is_normal(vault, mod, terminal):
    reply = mod("commands").handle("", platform="cli", vault=vault)
    assert not reply.startswith("MyFolks is ready.")
