"""Plain words for every action, a next step in every reply, no dead ends, help as jobs."""
from types import SimpleNamespace

import pytest


@pytest.fixture
def run(vault, mod):
    def run(text, answer=None, platform="desktop"):
        return mod("commands").handle(text, platform=platform, vault=vault, ask=lambda _q, _c: answer)

    return run


def lines_of(vault, name):
    with vault.read() as connection:
        return [row[0] for row in connection.execute(
            "SELECT text FROM details JOIN cards ON cards.id=details.card_id WHERE cards.name=? AND details.closed_at IS NULL ORDER BY details.id", (name,))]


def live_names(vault):
    with vault.read() as connection:
        return sorted(row[0] for row in connection.execute("SELECT name FROM cards WHERE closed_at IS NULL"))


# 1. Plain words, one list in one place.

@pytest.mark.parametrize("word", ["remember", "save", "keep", "note", "add", "Remember", "note:"])
def test_save_words(run, vault, word):
    run(f"{word} Priya likes tea")
    assert lines_of(vault, "Priya") == ["likes tea"]


@pytest.mark.parametrize("word", ["forget", "delete", "remove"])
def test_delete_words(run, vault, word):
    run("save Priya likes tea")
    run(f"{word} Priya")
    assert live_names(vault) == []


@pytest.mark.parametrize("word", ["fix", "change", "edit", "correct", "update"])
def test_correct_words(run, vault, word):
    run("save Priya likes tea")
    assert run(f"{word} Priya").splitlines()[1] == "1. likes tea"
    run(f"{word} Priya 1 likes green tea")
    assert lines_of(vault, "Priya") == ["likes green tea"]


@pytest.mark.parametrize("text", ["help", "commands", "?", "what can you do", "What can you do?", "how do I save someone", "HELP"])
def test_help_words(run, mod, text):
    assert run(text) == mod("messages").help_text("owner")


@pytest.mark.parametrize("word", ["history", "changes"])
def test_history_words(run, word):
    run("save Priya likes tea")
    assert run(f"{word} Priya").startswith("Priya: history")


def test_undo_and_sync_words(run, vault):
    run("save Priya likes tea")
    assert run("undo").startswith("Undone: ")
    assert run("sync off").startswith("Google sync is off.")


@pytest.mark.parametrize("name", ["Note", "Change", "Will"])
def test_a_saved_persons_exact_name_wins_over_a_verb(run, vault, name):
    run(f'save --new "{name}" plays cello')
    assert run(f"{name.lower()} cello").startswith(name)  # read as a lookup, not a command
    assert lines_of(vault, name) == ["plays cello"]


def test_a_first_name_nickname_wins_too(run, vault):
    run('save "Mark Lee" plays cello')
    assert run("mark cello").startswith("Mark Lee")


def test_plain_words_work_with_the_wake_word(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    wake = mod("wake")
    command = wake.rewrite("myfolks forget Priya", "myfolks")
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    mod("commands").handle(command[len("/contacts"):].strip(), platform="telegram", source=source, vault=vault)
    assert live_names(vault) == []


def test_shared_people_may_ask_for_help_but_not_delete(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111", "222"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    source = SimpleNamespace(user_id="222", chat_type="dm", is_bot=False)
    send = lambda text: mod("commands").handle(text, platform="telegram", source=source, vault=vault, shared="telegram:222:read")  # noqa: E731
    assert send("help") == mod("messages").help_text("read")
    assert send("forget Priya") == "MyFolks isn't available here."
    assert live_names(vault) == ["Priya"]


# 2. Every reply teaches the next step, in the surface's own prefix.

@pytest.fixture
def phone(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)

    def send(text, wake_word="myfolks"):
        return mod("commands").handle(text, platform="telegram", source=source, vault=vault, wake_word=wake_word)

    return send


def test_next_step_lines_in_a_chat_app_use_the_wake_word(phone):
    assert phone("remember Melisa likes tea") == "New card for Melisa. Saved. Undo: myfolks undo"
    assert phone("remember Melisa has a dog") == "Saved to Melisa. Undo: myfolks undo"
    assert phone("fix Melisa 1 likes green tea") == "Changed. Undo: myfolks undo"
    assert phone("melisa").splitlines()[-1] == "Change a line: myfolks fix Melisa    Delete: myfolks forget Melisa"
    assert phone("forget Melisa 2") == "Deleted line 2 from Melisa. Undo: myfolks undo"
    assert phone("forget Melisa") == "Deleted Melisa. Undo: myfolks undo"


def test_a_custom_wake_word_is_the_prefix(phone):
    assert phone("remember Melisa likes tea", wake_word="folks") == "New card for Melisa. Saved. Undo: folks undo"


def test_wake_word_off_and_the_terminal_use_slash_myfolks(phone, vault, mod):
    assert phone("remember Melisa likes tea", wake_word="") == "New card for Melisa. Saved. Undo: /myfolks undo"
    assert mod("commands").handle("remember Melisa has a dog", platform="desktop", vault=vault, wake_word="myfolks") == "Saved to Melisa. Undo: /myfolks undo"


def test_shared_people_see_no_change_or_delete_line(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111", "222"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    source = SimpleNamespace(user_id="222", chat_type="dm", is_bot=False)
    view = mod("commands").handle("priya", platform="telegram", source=source, vault=vault, shared="telegram:222:read", wake_word="myfolks")
    assert "forget" not in view and "fix" not in view



# 3. No dead ends.

def test_a_statement_that_finds_nothing_gets_the_save_command(run, vault):
    run("save Melisa likes tea")
    assert run("Melisa's dog's name is Ollie") == "Nothing saved about that yet. To save it, send:\n/myfolks remember Melisa's dog's name is Ollie"
    assert lines_of(vault, "Melisa") == ["likes tea"]  # never saved on a guess


@pytest.mark.parametrize("text", ["rositah is vegetarian", "Sam has two kids", "Ana likes jazz"])
def test_statements_about_new_people_too(run, vault, text):
    assert run(text) == f"Nothing saved about that yet. To save it, send:\n/myfolks remember {text}"
    assert live_names(vault) == []


@pytest.mark.parametrize("text", ["what's Melisa's dog called?", "is Melisa vegetarian", "Tom's birthday", "melisa shoe size"])
def test_questions_keep_their_reply_and_get_the_help_pointer(run, text):
    run("save Melisa likes tea")
    reply = run(text)
    assert reply.endswith("\nNot sure what to send? /myfolks help") and "To save it" not in reply


def test_on_telegram_the_command_is_a_copy_block_with_the_wake_word(phone):
    assert phone("Melisa's dog's name is Ollie") == "Nothing saved about that yet. To save it, send:\n`myfolks remember Melisa's dog's name is Ollie`"
    assert phone("zed") == "No one called zed yet.\nNot sure what to send? myfolks help"


def test_people_who_may_only_read_get_the_help_pointer_not_a_save(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111", "222"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    source = SimpleNamespace(user_id="222", chat_type="dm", is_bot=False)
    reply = mod("commands").handle("Sam has two kids", platform="telegram", source=source, vault=vault, shared="telegram:222:read")
    assert reply.endswith("Not sure what to send? /myfolks help") and "remember" not in reply


# 4. Help as jobs, and the short overview.

HELP = """Just talk to MyFolks. Start with myfolks:

myfolks what's Priya's dog called?
myfolks remember Priya is allergic to peanuts
myfolks fix Priya (pick a line to change)
myfolks forget Priya
myfolks undo (your last change)
myfolks sync (bring in your Google contacts)

To see and manage everyone, open MyFolks in Hermes Desktop."""


def test_help_for_the_owner_in_a_chat_app(phone):
    assert phone("help") == HELP


def test_help_in_the_terminal_uses_slash_myfolks(run):
    assert run("help") == HELP.replace("myfolks", "/myfolks").replace("/myfolks in Hermes", "MyFolks in Hermes").replace("Open /MyFolks", "open MyFolks")


def test_help_for_shared_people_shows_only_their_lines(mod):
    messages = mod("messages")
    assert messages.help_text("read") == "Just talk to MyFolks. Start with /myfolks:\n\n/myfolks what's Priya's dog called?"
    assert messages.help_text("add").splitlines()[-1] == "/myfolks remember Priya is allergic to peanuts"


def test_overview_with_people_saved(phone, vault, mod):
    phone("remember Priya likes tea")
    reply = phone("")
    assert reply.splitlines()[:2] == ["MyFolks: 1 saved. Ask or save in plain words, like: myfolks what's Priya's dog called?", "More: myfolks help"]
    assert mod("messages").overview(1040).splitlines()[0].startswith("MyFolks: 1,040 saved.")


def test_the_example_question_in_help_really_works(run):
    run("save Priya dog is Biscuit")
    run("save Biscuit is a golden retriever")
    reply = run("what's Priya's dog called?")
    assert reply.startswith("Priya\n") and "dog is Biscuit" in reply


# 5. The user guide lists only words that work.

def _readme_guide():
    from pathlib import Path

    text = (Path(__file__).parent.parent / "README.md").read_text()
    return text.split("## User guide\n", 1)[1].split("\n## ", 1)[0]


def test_readme_user_guide_comes_first_and_every_word_works(mod):
    import re

    readme = (__import__("pathlib").Path(__file__).parent.parent / "README.md").read_text()
    assert readme.index("## User guide") < readme.index("## Quick start")
    guide = _readme_guide()
    assert guide.lstrip().startswith("Start a chat message with **myfolks** (or /myfolks), then use plain words.")
    verbs = mod("commands")._VERB_WORDS
    rows = [line.split("|")[1:4] for line in guide.splitlines() if line.startswith("| ") and not line.startswith("| To ")]
    assert [row[0].strip() for row in rows] == ["Ask", "Save", "Fix", "Delete", "Undo", "Connect", "Bring people in", "See changes", "Help"]
    for _to, words, _example in rows[1:]:
        for word in re.findall(r"[a-z]+", words):
            assert word in verbs, word
    assert "In Hermes Desktop, open MyFolks to search, add, edit, delete and undo with buttons." in guide


def test_every_readme_example_runs(run, vault):
    import re

    run("save Priya dog is Biscuit")
    run("save Biscuit is a golden retriever")
    for example in re.findall(r"`myfolks ([^`]+)`", _readme_guide()):
        reply = run(example)
        assert not reply.startswith(("To ", "MyFolks isn't")), (example, reply)


def test_desktop_guide_lists_the_same_words(mod):
    import re
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    assert "guideTitle: 'How to use'," in js and "jsx(Guide, { word })" in js and "render: () => jsx(SettingsPage, { ctx })" in js
    verbs = mod("commands")._VERB_WORDS
    rows = re.findall(r"\{ to: '([^']+)', words: \[([^\]]+)\]", js)
    assert [to for to, _ in rows] == ["Ask", "Save", "Fix", "Delete", "Undo", "Connect", "Bring people in", "See changes", "Help"]
    for to, words in rows[1:]:
        for word in re.findall(r"'([a-z]+)'", words):
            assert word in verbs, (to, word)


def test_desktop_status_gives_the_wake_word(vault, mod, monkeypatch):
    wake = mod("wake")
    assert wake.configured_word(lambda: {"plugins": {"entries": {"myfolks": {"settings": {"wake_word": "Folks"}}}}}) == "folks"
    assert wake.configured_word(lambda: {"plugins": {"entries": {"myfolks": {"settings": {"wake_word": ""}}}}}) == ""
    assert wake.configured_word(lambda: {}) == "myfolks"
    monkeypatch.setattr(wake, "configured_word", lambda: "folks")
    assert mod("desktop_service").status(vault=vault)["wake_word"] == "folks"
