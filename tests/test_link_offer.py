import pytest


@pytest.fixture
def run(vault, mod):
    def run(text, answer="unset", **kw):
        asked = []

        def ask(question, choices):
            asked.append((question, [c["label"] for c in choices]))
            return None if answer == "unset" else answer

        reply = mod("commands").handle(text, platform="desktop", vault=vault, ask=ask, **kw)
        run.asked = asked
        return reply

    return run


def links(vault):
    with vault.read() as connection:
        return [tuple(row) for row in connection.execute(
            "SELECT a.name, links.relation, b.name FROM links JOIN cards a ON a.id=from_card JOIN cards b ON b.id=to_card WHERE links.closed_at IS NULL")]


@pytest.mark.parametrize("words", ["dog is called Ollie", "Dog is called Ollie", "dog is named Ollie", "dog named Ollie"])
def test_offer_and_link(run, vault, words):
    run("save Mel likes tea")
    reply = run(f"save Mel {words}", answer="link")
    assert run.asked == [("Also link Ollie as Mel's dog?", ["Link", "Not now"])]
    assert reply.startswith("Saved to Mel.\nLinked: Mel, dog, Ollie.")
    assert links(vault) == [("Mel", "dog", "Ollie")]


def test_possessive_save_offers_the_link(run, vault):
    run("save Mel likes tea")
    reply = run("save Mel's dog is called Ollie", answer="link")
    assert run.asked[0][0] == "Also link Ollie as Mel's dog?"
    assert "Linked: Mel, dog, Ollie." in reply
    assert run("mel dog") == "Ollie\nDog of Mel\nNo lines saved yet.\nChange a line: /myfolks fix Ollie    Delete: /myfolks forget Ollie"
    assert run("mel dog called").startswith("Ollie\nDog of Mel")  # "called" carries no meaning in a question


def test_not_now_links_nothing(run, vault):
    run("save Mel likes tea")
    assert run("save Mel dog is called Ollie", answer="not-now") == "Saved to Mel. Undo: /myfolks undo"
    assert links(vault) == []


def test_no_way_to_ask_gives_the_save_reply_alone(vault, mod):
    handle = mod("commands").handle
    handle("save Mel likes tea", platform="desktop", vault=vault)
    reply = handle("save Mel dog is called Ollie", platform="desktop", vault=vault)
    assert reply == "Saved to Mel. Undo: /myfolks undo"
    assert links(vault) == []


def test_unanswered_question_gives_the_save_reply_alone(run, vault):
    run("save Mel likes tea")
    assert run("save Mel dog is called Ollie") == "Saved to Mel. Undo: /myfolks undo"
    assert run.asked == [("Also link Ollie as Mel's dog?", ["Link", "Not now"])]


@pytest.mark.parametrize("words", ["dog is ollie", "likes dogs", "dog is a beagle", "walks the dog", "hotdog is Big", "dogma is Strict"])
def test_no_offer_without_a_relation_and_capitalized_name(run, words):
    run("save Mel likes tea")
    assert run(f"save Mel {words}") == "Saved to Mel. Undo: /myfolks undo"
    assert run.asked == []


def test_no_offer_when_already_linked(run, vault):
    run("save Mel likes tea")
    run("link Mel dog Ollie")
    assert run("save Mel dog's name Ollie") == "Saved to Mel. Undo: /myfolks undo"
    assert run.asked == []


def test_near_name_link_target_still_asks(run, vault):
    run("save Mel likes tea")
    run("save Bisquit is a beagle")
    reply = run("save Mel dog is Biscuit", answer="link")
    assert run.asked[1][0] == "Did you mean Bisquit?"


def test_shared_reader_gets_no_offer(vault, mod, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111", "222"}, False))
    handle = mod("commands").handle
    handle("save Mel likes tea", platform="desktop", vault=vault)
    sender = SimpleNamespace(user_id="222", chat_type="dm", is_bot=False)
    reply = handle("save Mel dog is Ollie", platform="telegram", source=sender, vault=vault, shared="telegram:222:add")
    assert reply == "Saved to Mel. Undo: /myfolks undo"


def test_undo_after_link_removes_the_link_only(run, vault):
    run("save Mel likes tea")
    run("save Mel dog is Ollie", answer="link")
    run("undo")
    assert links(vault) == []
    assert "dog is Ollie" in run("mel dog")
