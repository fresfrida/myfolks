"""Link without asking only when it cannot be wrong; ask in every other case."""
import json

import pytest


@pytest.fixture
def run(vault, mod):
    handle = mod("commands").handle
    handle("save Mel likes tea", platform="cli", vault=vault)

    def run(text, answer=None):
        asked = []

        def ask(question, choices):
            asked.append(question)
            return answer

        reply = handle(text, platform="desktop", vault=vault, ask=ask)
        run.asked = asked
        return reply

    return run


def links(vault):
    with vault.read() as connection:
        return [tuple(row) for row in connection.execute(
            "SELECT a.name, links.relation, b.name FROM links JOIN cards a ON a.id=from_card JOIN cards b ON b.id=to_card WHERE links.closed_at IS NULL")]


@pytest.mark.parametrize("words", ["dog's name Ollie", "dog's name is Ollie", "dog is Ollie", "dog Ollie", "dog’s name Ollie", 'dog is "Ollie Moon"', "Dog is Ollie"])
def test_plain_forms_link_without_asking(run, vault, words):
    reply = run(f"save Mel {words}")
    target = "Ollie Moon" if "Moon" in words else "Ollie"
    assert reply == f"Saved to Mel.\nLinked {target} as Mel's dog. Undo: /contacts undo"
    assert run.asked == []
    assert links(vault) == [("Mel", "dog", target)]


def test_links_to_an_existing_exact_card(run, vault):
    run("save Ollie is a beagle")
    assert run("save Mel dog is Ollie").endswith("Linked Ollie as Mel's dog. Undo: /contacts undo")
    with vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM cards WHERE name='Ollie'").fetchone()[0] == 1


def test_near_name_asks_instead(run, vault):
    run("save Olliee is a beagle")
    reply = run("save Mel dog is Ollie")
    assert run.asked == ["Also link Ollie as Mel's dog?"]
    assert "Linked" not in reply and links(vault) == []


def test_two_cards_with_that_name_asks(run, vault, mod):
    with vault.write() as connection:
        change = mod("db").Change(connection, "save", "terminal")
        mod("cards").add_card(change, "Ollie", "terminal")
        mod("cards").add_card(change, "Ollie", "terminal")
        change.finish("two Ollies")
    run("save Mel dog is Ollie")
    assert run.asked == ["Also link Ollie as Mel's dog?"] and links(vault) == []


@pytest.mark.parametrize("words", ["dog is scared of Ollie", "dog is ollie", "dog is Ollie Moon", "my dog is Ollie", "dog is Ollie.", "dog is called Ollie", "likes Ollie"])
def test_unclear_sentences_never_link_on_their_own(run, vault, words):
    reply = run(f"save Mel {words}")
    assert "Linked" not in reply and links(vault) == []


def test_new_person_asks_instead(run, vault):
    reply = run("save Zed dog is Ollie")
    assert reply.startswith("New card for Zed. Saved.") and "Linked" not in reply
    assert run.asked == ["Also link Ollie as Zed's dog?"]


def test_near_person_confirmed_still_asks_for_link(run, vault):
    run("save Marcus likes tea")
    run("save Markus dog is Ollie", answer=None)
    assert links(vault) == []


def test_first_undo_removes_only_the_link(run, vault, mod):
    run("save Mel dog is Ollie")
    assert run("undo") == "Undone: linked Mel, dog, Ollie."
    assert links(vault) == []
    assert "dog is Ollie" in run("mel dog")
    assert run("undo") == "Undone: saved to Mel."


def test_wake_word_and_myfolks_link_the_same_way(vault, mod, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    wake = mod("wake")
    hook = wake.gateway_hook(wake.Settings(lambda key, default=None: default))
    mod("commands").handle("save Mel likes tea", platform="cli", vault=vault)
    command = hook(event=SimpleNamespace(text="myfolks remember Mel's dog's name Ollie"))["text"]
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = mod("commands").handle(command[len("/contacts"):].strip(), platform="telegram", source=source, vault=vault)
    assert reply == "Saved to Mel.\nLinked Ollie as Mel's dog. Undo: /contacts undo"


def test_ai_tool_links_the_same_way(vault, mod):
    mod("commands").handle("save Mel likes tea", platform="cli", vault=vault)
    told = []
    reply = json.loads(mod("ai_tool").handle({"action": "save", "name": "Mel", "text": "dog is Ollie"}, vault=vault, tell_user=told.append, session=("cli", None)))
    assert reply["status"] == "saved"
    assert told == ['MyFolks saved to Mel: "dog is Ollie"\nLinked Ollie as Mel\'s dog. Undo: /contacts undo']
    assert links(vault) == [("Mel", "dog", "Ollie")]
    told.clear()
    json.loads(mod("ai_tool").handle({"action": "save", "name": "Mel", "text": "cat is called Tom"}, vault=vault, tell_user=told.append, session=("cli", None)))
    assert "Linked" not in told[0]
