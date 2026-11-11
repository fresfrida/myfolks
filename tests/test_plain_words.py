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
