"""Save never files details under a detail word, never guesses a new person once contacts are imported,
and a save reply on Telegram is the save reply alone."""
import pytest

from test_ingress import setup  # noqa: F401  (the real register() and wake-word hook, a fake Telegram adapter)

QUESTION = "Who is this for? Start with their name, like:\nmyfolks save Priya {} ..."


@pytest.fixture
def run(vault, mod):
    def run(text, answer=None, **kw):
        asked = []

        def ask(question, choices):
            asked.append((question, [c["label"] for c in choices]))
            return answer

        reply = mod("commands").handle(text, platform="desktop", vault=vault, ask=ask, **kw)
        run.asked = asked
        return reply

    return run


def card_names(vault):
    with vault.read() as connection:
        return sorted(row[0] for row in connection.execute("SELECT name FROM cards"))


def do_import(vault, mod, *names):
    importer = mod("importer")
    with vault.write() as connection:
        importer.apply_contacts(connection, [importer.Incoming(name=name, phones=["555 0100"]) for name in names], "test import")


# 1. A detail word is never a name.

@pytest.mark.parametrize("text, word", [
    ("save address Sis Nel Address Type Residential", "address"),
    ("save Phone: 555 1234", "Phone:"),
    ("save Email x@y.z", "Email"),
    ("save BIRTHDAY March 3", "BIRTHDAY"),
])
def test_detail_word_makes_no_card_and_asks_who(run, vault, text, word):
    assert run(text) == QUESTION.format(word)
    assert card_names(vault) == []
    assert run.asked == []


@pytest.mark.parametrize("text, name", [("save Melisa's dog's name is Ollie", "Melisa"), ("save rositah is vegetarian", "rositah")])
def test_normal_new_names_still_make_a_card(run, vault, text, name):
    assert run(text) == f"New card for {name}. Saved."
    assert card_names(vault) == [name]


def test_new_flag_still_makes_a_detail_word_card(run, vault):
    assert run('save --new "address" Sis Nel lives here') == "New card for address. Saved."
    assert card_names(vault) == ["address"]


def test_existing_card_named_address_still_saves_to_it(run, vault):
    run("save --new address first line")
    assert run("save address second line") == "Saved to address."
    assert card_names(vault) == ["address"]


def test_detail_word_on_telegram(setup):
    setup.send("myfolks save address Sis Nel Address Type Residential")
    assert setup.adapter.sent == [("c1", QUESTION.format("address"))]


# 2. The exact message the Owner sent, through the wake-word hook on Telegram: one reply, no stray line.

@pytest.mark.parametrize("before", [[], ["save Melisa likes tea", "save --new address Sis Nel lives here"]])
def test_wake_word_save_replies_once_without_a_stray_line(setup, mod, before):
    for text in before:
        mod("commands").handle(text, platform="cli", vault=setup.vault)
    assert setup.send("myfolks save rositah is vegetarian") == {"action": "skip", "reason": "answered by MyFolks"}
    assert setup.adapter.sent == [("c1", "New card for rositah. Saved.")]


# 3. No link tip after a save where MyFolks can't ask.

def test_telegram_save_naming_a_dog_is_the_save_reply_alone(setup):
    setup.send("myfolks save Melisa's dog's name is Ollie")
    assert setup.adapter.sent == [("c1", "New card for Melisa. Saved.")]


# 4. No new person on a guess once contacts are imported.

def test_imported_store_on_telegram_saves_nothing_and_gives_the_command(setup, mod):
    do_import(setup.vault, mod, "Melisa Tan")
    setup.send("myfolks save Rositah is vegetarian")
    assert setup.adapter.sent == [("c1", "Rositah isn't in your contacts yet. Nothing was saved. To go ahead, send:\nmyfolks save --new Rositah is vegetarian")]
    assert "Rositah" not in card_names(setup.vault)


def test_imported_store_asks_once_and_new_person_makes_the_card(run, vault, mod):
    do_import(vault, mod, "Melisa Tan")
    assert run("save Rositah is vegetarian", answer="new") == "New card for Rositah. Saved."
    assert run.asked == [("Rositah isn't in your contacts yet.", ["New person: Rositah", "Cancel"])]
    assert "Rositah" in card_names(vault)


def test_imported_store_cancel_saves_nothing(run, vault, mod):
    do_import(vault, mod, "Melisa Tan")
    assert run("save Rositah is vegetarian", answer="cancel") == "Nothing was changed."
    assert card_names(vault) == ["Melisa Tan"]


def test_imported_store_new_flag_still_creates(run, vault, mod):
    do_import(vault, mod, "Melisa Tan")
    assert run("save --new Rositah is vegetarian") == "New card for Rositah. Saved."
    assert run.asked == []


def test_imported_exact_name_saves_directly(run, vault, mod):
    do_import(vault, mod, "Rositah")
    assert run("save rositah is vegetarian") == "Saved to Rositah."
    assert run.asked == []


def test_imported_store_detail_word_still_asks_who(run, vault, mod):
    do_import(vault, mod, "Melisa Tan")
    assert run("save address Sis Nel") == QUESTION.format("address")
    assert run.asked == []


def test_no_import_makes_the_card_as_before(run, vault):
    run("save Melisa likes tea")
    assert run("save Rositah is vegetarian") == "New card for Rositah. Saved."
    assert run.asked == []


def test_undone_import_counts_as_no_import(run, vault, mod):
    do_import(vault, mod, "Melisa Tan")
    assert run("undo").startswith("Undone:")
    assert run("save Rositah is vegetarian") == "New card for Rositah. Saved."
    assert run.asked == []
