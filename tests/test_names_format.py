from types import SimpleNamespace
import argparse
import io

import pytest


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def phone(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    return lambda text, **kw: mod("commands").handle(text, platform="telegram", source=source, vault=vault, **kw)


@pytest.fixture
def run(vault, mod):
    return lambda text: mod("commands").handle(text, platform="cli", vault=vault)


def names(vault):
    with vault.read() as connection:
        return [row[0] for row in connection.execute("SELECT name FROM cards ORDER BY id")]


def test_name_with_newline_is_one_line_on_save(run, vault):
    run('save "Mel\nOrtiz" likes tea')
    assert names(vault) == ["Mel Ortiz"]


def test_name_with_control_characters_on_link(run, vault):
    run("save Mel likes tea")
    run('link Mel dog "Ol\x07lie\r\nBoy"')
    assert names(vault) == ["Mel", "Ol lie Boy"]


def test_name_with_newline_on_import(vault, mod, tmp_path):
    card = tmp_path / "x.vcf"
    card.write_text("BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Mel\\nOrtiz\r\nNICKNAME:Me\\nlly\r\nEND:VCARD\r\n")
    assert mod("cli").cmd_import(argparse.Namespace(path=str(card)), vault=vault, stdin=Terminal(), stdout=Terminal()) == 0
    assert names(vault) == ["Mel Ortiz"]
    with vault.read() as connection:
        assert "\n" not in "".join(row[0] for row in connection.execute("SELECT alias FROM aliases"))


def test_name_of_only_control_characters_is_refused(run, vault):
    assert run('save "\n\t" likes tea') == "To save: /contacts save <name> <text>"
    assert names(vault) == []


def test_name_with_formatting_characters_on_telegram(phone, vault):
    phone('save "Mel_*x" likes tea')
    assert phone('"Mel_*x"').split("\n")[0] == "`Mel_*x`"
    assert phone('"Mel_*x" tea').split("\n")[0] == "`Mel_*x`"
    assert phone('"Mel_*x" coffee tea').split("\n")[0] in ("`Mel_*x`", "`Mel_*x` · not sure")


def test_unsure_heading_with_formatting_name(mod):
    messages = mod("messages")
    with messages.replies_for("Telegram"):
        out = messages.answer("Mel_x", [("likes tea", "2026-01-01T00:00:00+00:00", "Telegram")], True, messages.telegram_words)
    assert out.split("\n")[0] == "`Mel_x` · not sure"


def test_more_line_protects_name(mod):
    messages = mod("messages")
    with messages.replies_for("Telegram"):
        assert messages.more_line(3, "Mel_x") == "+3 more · /contacts `Mel_x`"
        assert messages.more_line(3, "Mel") == "+3 more · /contacts Mel"
    assert messages.more_line(3, "Mel_x") == "+3 more · /contacts Mel_x"


def test_plain_names_unchanged_on_telegram(phone):
    phone("save Mel likes tea")
    assert phone("mel tea") .split("\n")[0] == "Mel"
    assert phone("mel").split("\n")[0] == "Mel"


@pytest.mark.parametrize("text, fence", [("a ```b``` c", "````"), ("one `tick`", "```"), ("x ````` y", "``````"), ("two\nlines", "```")])
def test_fence_is_longer_than_any_backtick_run(mod, text, fence):
    out = mod("messages").telegram_words(text)
    assert out == f"{fence}\n{text}\n{fence}"


def test_line_with_triple_backticks_on_telegram(phone):
    phone("save Mel uses ```code``` blocks")
    reply = phone("mel code")
    assert "````\nuses ```code``` blocks\n````" in reply
