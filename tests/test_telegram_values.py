"""Every value put into a Telegram reply shows literally: names, relations, aliases, sources, summaries, commands."""
import argparse
import inspect
import io
import re
from types import SimpleNamespace

import pytest

NAME = "Mel_*x"
RELATION = "*dog_"
HOSTILE = (NAME, RELATION)
_PIECES = ("Mel_", "_*", "*x", "*dog", "dog_")  # any raw part of a hostile value outside code
_CODE = re.compile(r"(`{3,})\n.*?\n\1|`[^`\n]+`", re.S)


def shows_literally(reply: str) -> bool:
    """Telegram shows text inside a code span or fence exactly. Outside them, no hostile value may appear."""
    outside = _CODE.sub("", reply)
    return not any(piece in outside for piece in _PIECES)


def test_checker_catches_raw_values():
    assert not shows_literally(f"Saved to {NAME}.")
    assert shows_literally(f"Saved to `{NAME}`.")


# Every template that puts a value into a reply. A new one must be added here or to RAW_BY_DESIGN.
TEMPLATES = {
    "saved": lambda m: m.saved(NAME),
    "new_card": lambda m: m.new_card(NAME),
    "card_heading": lambda m: m.card_heading(NAME),
    "more_line": lambda m: m.more_line(3, NAME),
    "answer": lambda m: m.answer(NAME, [("likes tea", "2026-01-01T00:00:00+00:00", RELATION)], True, m.telegram_words, more=2),
    "choose_fallback": lambda m: m.choose_fallback([(1, NAME, RELATION), (2, NAME, "")]),
    "choose_names_fallback": lambda m: m.choose_names_fallback([NAME, NAME]),
    "linked": lambda m: m.linked(NAME, RELATION, NAME, [NAME]),
    "alias_added": lambda m: m.alias_added(NAME, RELATION),
    "undone": lambda m: m.undone(f"linked {NAME}, {RELATION}, Ollie"),
    "undo_blocked": lambda m: m.undo_blocked(f"imported from {NAME}.vcf import"),
    "done": lambda m: m.done(f"merged {NAME}"),
    "link_line": lambda m: m.link_line(RELATION, NAME, True) + "\n" + m.link_line(RELATION, NAME, False),
    "history_line": lambda m: m.history_line("likes tea", "2026-01-01T00:00:00+00:00", RELATION, None, m.telegram_plain),
    "history_title": lambda m: m.history_title(NAME),
    "review_entry": lambda m: m.review_entry(1, NAME, [f"phone {RELATION}"], [(2, NAME)]),
    "who_is_this_for": lambda m: m.who_is_this_for(NAME),
    "not_in_contacts": lambda m: m.not_in_contacts(NAME),
    "new_person_choice": lambda m: m.new_person_choice(NAME),
    "not_in_contacts_fallback": lambda m: m.not_in_contacts_fallback(NAME, f"myfolks save --new {NAME} {RELATION}"),
    "did_you_mean_open": lambda m: m.did_you_mean_open(m.did_you_mean(NAME), [f"/contacts {NAME}"]),
    "did_you_mean_fallback": lambda m: m.did_you_mean_fallback(m.did_you_mean(NAME), [f"/contacts save {NAME} x"]),
    "hidden_only": lambda m: m.hidden_only(NAME),
    "no_one_called": lambda m: m.no_one_called(NAME),
    "setup_note": lambda m: m.setup_note("2026-01-01T00:00:00+00:00", NAME),
    "did_you_mean": lambda m: m.did_you_mean([NAME, NAME + "s"]),
    "new_card_choice": lambda m: m.new_card_choice(NAME),
    "choice_label": lambda m: m.choice_label(NAME, 3) + "\n" + m.choice_label(NAME),
    "link_offer": lambda m: m.link_offer(NAME, NAME, RELATION),
    "auto_linked": lambda m: m.auto_linked(NAME, NAME, RELATION),
    "ai_saved": lambda m: m.ai_saved(NAME, f"{RELATION} is Ollie"),
}

# Text that never reaches Telegram: terminal prompts, the AI's own note, and Desktop JSON.
RAW_BY_DESIGN = {
    "ai_wake_note", "pair_ask_replace", "busy_use_wake_word",
    "pair_instruction", "receipt", "telegram_words", "telegram_plain", "value", "replies_for", "date_label",
    "import_summary", "import_stopped", "import_aliases", "overview", "notes_line", "numbered_line", "hidden_count_line",
    "hide_list_line", "review_title", "backup_done",
}


# Templates that take only numbers: no saved or typed value can reach them.
NUMBERS_ONLY = {"sync_summary", "sync_first"}


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_template_shows_values_literally(mod, template):
    messages = mod("messages")
    with messages.replies_for("Telegram"):
        reply = TEMPLATES[template](messages)
    assert shows_literally(reply), reply
    assert NAME in reply or RELATION in reply


def test_every_value_template_is_covered(mod):
    messages = mod("messages")
    public = {name for name, item in vars(messages).items() if inspect.isfunction(item) and not name.startswith("_") and item.__module__ == messages.__name__}
    assert public - set(TEMPLATES) - RAW_BY_DESIGN - NUMBERS_ONLY == set()


def test_terminal_values_stay_plain(mod):
    messages = mod("messages")
    assert messages.saved(NAME) == f"Saved to {NAME}."


@pytest.fixture
def phone(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    return lambda text, **kw: mod("commands").handle(text, platform="telegram", source=source, vault=vault, **kw)


def literal(reply):
    assert shows_literally(reply), reply
    return reply


def test_every_command_reply_on_telegram(phone, vault, mod):
    replies = [
        literal(phone(f'save "{NAME}" likes tea')),
        literal(phone(f'save "{NAME}" {RELATION} is Ollie')),
        literal(phone(f'link "{NAME}" "{RELATION}" Ollie')),
        literal(phone(f'link "{NAME}" aka "{RELATION}x"')),
        literal(phone(f'"{NAME}"')),
        literal(phone("ollie")),
        literal(phone(f'"{NAME}" tea')),
        literal(phone(f'"{NAME}" coffee tea')),
        literal(phone(f'history "{NAME}"')),
        literal(phone(f'correct "{NAME}"')),
        literal(phone(f'correct "{NAME}" 1 likes green tea')),
        literal(phone("undo")),
        literal(phone(f'"{NAME}q" tea')),
        literal(phone(f'save "{NAME}q" likes jam')),
    ]
    assert any(f"`{NAME}`" in reply for reply in replies)
    assert any(f"`{RELATION}`" in reply for reply in replies)


def test_many_lines_and_hidden_only_on_telegram(phone, vault, mod):
    for number in range(10):
        phone(f'save "{NAME}" likes tea {number}')
    literal(phone(f'"{NAME}" tea'))
    from loader import save_hidden

    mod("commands").handle('save "Zed_*y" first', platform="cli", vault=vault)
    save_hidden(vault, "Zed_*y keeps a secret")
    reply = phone('"Zed_*y" secret')
    assert "`Zed_*y`" in reply


def test_review_and_choose_on_telegram(phone, vault, mod, tmp_path):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    card = tmp_path / "x.vcf"
    card.write_text(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{NAME}\r\nTEL:+1 202 555 0101\r\nEND:VCARD\r\n"
                    f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{NAME} Ortiz\r\nTEL:+1 202 555 0102\r\nEND:VCARD\r\n")
    mod("cli").cmd_import(argparse.Namespace(path=str(card)), vault=vault, stdin=Terminal(), stdout=Terminal())
    literal(phone("review"))
    mod("commands").handle(f'save --new "{NAME}" second card', platform="cli", vault=vault)
    literal(phone(f'"{NAME}"'))


def test_questions_and_buttons_on_telegram(phone, vault, mod):
    mod("commands").handle(f'save "{NAME}" likes tea', platform="cli", vault=vault)
    mod("commands").handle(f'save --new "{NAME}s" likes jam', platform="cli", vault=vault)
    asked = []

    def ask(question, choices):
        asked.append(question)
        asked.extend(choice["label"] for choice in choices)
        asked.extend(choice.get("description") or "" for choice in choices)
        return None

    phone(f'"{NAME}z" tea', ask=ask)
    phone(f'save "{NAME}z" likes cake', ask=ask)
    phone(f'save "{NAME}" dog is called Ollie', ask=ask)
    assert asked and all(shows_literally(text) for text in asked), asked
    assert f"Also link Ollie as `{NAME}`'s dog?" in asked
    assert any(text.startswith("Did you mean `") for text in asked)


def test_ai_save_confirmation_on_telegram(vault, mod, monkeypatch):
    import json

    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    mod("commands").handle(f'save "{NAME}" likes tea', platform="cli", vault=vault)
    told = []
    sender = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = json.loads(mod("ai_tool").handle({"action": "save", "name": NAME, "text": f"{RELATION} is Ollie"}, vault=vault, tell_user=told.append, session=("telegram", sender)))
    assert reply["status"] == "saved"
    assert told and shows_literally(told[0]), told
    local = json.loads(mod("ai_tool").handle({"action": "save", "name": NAME, "text": "likes jam"}, vault=vault, tell_user=told.append, session=("cli", None)))
    assert local["tell_user"] == f'MyFolks saved to {NAME}: "likes jam"'


@pytest.mark.parametrize("text, expected", [
    ("likes tea", 'MyFolks saved to Mel: "likes tea"'),
    ("uses_snake case", "MyFolks saved to Mel: `uses_snake case`"),
    ("line one\nline two", "MyFolks saved to Mel:\n```\nline one\nline two\n```"),
    ("has ```fence``` inside", "MyFolks saved to Mel:\n````\nhas ```fence``` inside\n````"),
])
def test_ai_save_notice_has_no_quotes_around_code(mod, text, expected):
    messages = mod("messages")
    with messages.replies_for("Telegram"):
        assert messages.ai_saved("Mel", text) == expected
    assert messages.ai_saved("Mel", text) == f'MyFolks saved to Mel: "{text}"'


def test_ai_save_multiline_on_telegram_end_to_end(vault, mod, monkeypatch):
    import json

    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    mod("commands").handle("save Mel likes tea", platform="cli", vault=vault)
    told = []
    sender = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = json.loads(mod("ai_tool").handle({"action": "save", "name": "Mel", "text": "first line\nsecond line"}, vault=vault, tell_user=told.append, session=("telegram", sender)))
    assert reply["status"] == "saved"
    assert told == ["MyFolks saved to Mel:\n```\nfirst line\nsecond line\n```"]
