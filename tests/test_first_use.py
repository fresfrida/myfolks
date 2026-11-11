"""The recovery code appears only from hermes myfolks setup and the Desktop page's setup screen.
No chat, including terminal chat and Desktop chat, ever sets MyFolks up or prints the code."""
import io
import json
import re
from types import SimpleNamespace

import pytest

CODE = re.compile(r"[A-Z2-7]{4}(?:-[A-Z2-7]{4}){7}")
NOT_SET_UP = "Run hermes myfolks setup in your own terminal."


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def fresh(tmp_path, mod):
    return mod("vault").Vault(tmp_path / "data", keys=mod("device_key").DeviceKeys(tmp_path / "data", use_keychain=False))


@pytest.mark.parametrize("platform", ["cli", "tui", "local", "desktop", "telegram", "discord"])
@pytest.mark.parametrize("text", ["", "priya", "save Priya likes tea", "pair ABCD"])
def test_no_chat_surface_sets_up_or_prints_a_code(fresh, mod, monkeypatch, platform, text):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda _platform: ({"111"}, False))
    monkeypatch.setattr(mod("cli"), "_in_terminal", lambda _streams: True)
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = mod("commands").handle(text, platform=platform, source=source, vault=fresh)
    assert not CODE.search(reply) and not fresh.exists()
    if not text.startswith("pair"):
        assert reply == NOT_SET_UP


def test_wake_word_never_sets_up(fresh, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda _platform: ({"111"}, False))
    wake = mod("wake")
    command = wake.gateway_hook(wake.Settings(lambda key, default=None: default))(event=SimpleNamespace(text="myfolks remember Priya likes tea"))["text"]
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = mod("commands").handle(command[len("/contacts"):].strip(), platform="telegram", source=source, vault=fresh)
    assert reply == NOT_SET_UP and not fresh.exists()


def test_ai_tool_never_sets_up(fresh, mod):
    reply = mod("ai_tool").handle({"action": "lookup", "question": "priya"}, vault=fresh, session=("cli", None))
    assert json.loads(reply)["status"] == "not_set_up" and not CODE.search(reply) and not fresh.exists()


def test_hermes_myfolks_setup_shows_the_code_and_records_terminal(fresh, mod):
    out = Terminal()
    assert mod("cli").cmd_setup(None, vault=fresh, stdout=out) == 0
    code = CODE.search(out.getvalue()).group(0)
    assert fresh.check_recovery_code(code)
    assert mod("commands").handle("", platform="cli", vault=fresh) == mod("messages").EMPTY_OVERVIEW
    mod("commands").handle("save Priya likes tea", platform="cli", vault=fresh)
    overview = mod("commands").handle("", platform="cli", vault=fresh)
    assert overview.split("\n")[1:] == ["More: /myfolks help", "Set up today from terminal."]
    assert overview.startswith("MyFolks: 1 saved.")
    assert not CODE.search(overview)


def test_hermes_myfolks_setup_still_needs_a_real_terminal(fresh, mod):
    assert mod("cli").cmd_setup(None, vault=fresh, stdout=io.StringIO()) == 1
    assert not fresh.exists()


def test_desktop_page_setup_shows_the_code_once_and_records_it(fresh, mod):
    service = mod("desktop_service")
    first = service.setup(vault=fresh)
    assert CODE.fullmatch(first["code"]) and fresh.check_recovery_code(first["code"])
    assert service.setup(vault=fresh) == {"state": "ready"}
    mod("commands").handle("save Priya likes tea", platform="cli", vault=fresh)
    assert "Set up today from Desktop page." in mod("commands").handle("", platform="cli", vault=fresh)


def test_setup_note_on_telegram_is_protected(fresh, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda _platform: ({"111"}, False))
    mod("desktop_service").setup(vault=fresh)
    mod("commands").handle("save Priya likes tea", platform="cli", vault=fresh)
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    assert "Set up today from Desktop page." in mod("commands").handle("", platform="telegram", source=source, vault=fresh)


def test_old_store_without_a_record_shows_no_setup_line(vault, mod):
    assert "Set up" not in mod("commands").handle("", platform="cli", vault=vault)
