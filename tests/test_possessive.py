from types import SimpleNamespace

import pytest


@pytest.fixture
def run(vault, mod):
    return lambda text, **kw: mod("commands").handle(text, platform="cli", vault=vault, **kw)


@pytest.fixture
def phone(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    return lambda text, **kw: mod("commands").handle(text, platform="telegram", source=source, vault=vault, **kw)


def card_names(vault):
    with vault.read() as connection:
        return [row[0] for row in connection.execute("SELECT name FROM cards ORDER BY id")]


def test_possessive_save_goes_to_the_person(run, vault):
    run("save Mel likes tea")
    assert run("save Mel's dog's name Ollie").split("\n")[0] == "Saved to Mel."
    assert card_names(vault) == ["Mel"]
    assert "dog's name Ollie" in run("mel dog")


@pytest.mark.parametrize("typed", ["Mel's", "mel's", "Mel’s", "MEL'S"])
def test_possessive_spellings(run, vault, typed):
    run("save Mel likes tea")
    assert run(f"save {typed} dog's name Ollie").split("\n")[0] == "Saved to Mel."
    assert card_names(vault) == ["Mel"]


def test_trailing_apostrophe(run, vault):
    run("save James likes chess")
    assert run("save James' cat is Pixel").split("\n")[0] == "Saved to James."
    assert "cat is Pixel" in run("james cat")


def test_possessive_on_a_full_name(run, vault):
    run('save "Mel Ortiz" likes tea')
    assert run("save Mel Ortiz's dog's name Ollie").split("\n")[0] == "Saved to Mel Ortiz."


def test_new_person_from_possessive_gets_the_plain_name(run, vault):
    assert run("save Mel's dog's name Ollie").startswith("New card for Mel. Saved.")
    assert card_names(vault) == ["Mel"]
    assert "dog's name Ollie" in run("mel dog")


def test_real_name_ending_in_s_wins_when_exact(run, vault):
    run('save "Mel\'s" is a diner on Fifth')
    run("save Mel likes tea")
    assert run("save Mel's serves pancakes").split("\n")[0] == "Saved to Mel's."
    assert card_names(vault) == ["Mel's", "Mel"]
    assert "serves pancakes" not in run("mel")


def test_quoted_possessive_is_taken_as_written(run, vault):
    assert run('save "Mel\'s" serves pancakes').startswith("New card for Mel's. Saved.")
    assert card_names(vault) == ["Mel's"]


def test_near_name_still_asks_and_shows_nothing(run, vault):
    run("save Marcus likes tea")
    reply = run("save Markus's dog's name Ollie")
    assert reply.startswith("Did you mean Marcus?")
    assert "/contacts save --new Markus dog's name Ollie" in reply
    assert card_names(vault) == ["Marcus"]


def test_near_name_choice_saves_to_chosen_card(run, vault):
    run("save Marcus likes tea")
    assert run("save Markus's dog's name Ollie", ask=lambda question, choices: choices[0]["value"]).split("\n")[0] == "Saved to Marcus."


def test_possessive_link(run, vault):
    run("save Mel likes tea")
    run("save Ollie is a beagle")
    assert "Mel" in run("link Mel's dog Ollie")
    assert card_names(vault) == ["Mel", "Ollie"]
    assert "Dog: Ollie" in run("mel")


def test_possessive_on_chat(phone, vault):
    phone("save Mel likes tea")
    assert phone("save Mel's dog's name Ollie").split("\n")[0] == "Saved to Mel."
    assert "dog's name Ollie" in phone("mel dog")


def test_lookups_are_unchanged(run, vault):
    run("save Mel likes tea")
    assert run("mel's") == run("mel's")
