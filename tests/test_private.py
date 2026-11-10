import json
from types import SimpleNamespace

import pytest

PRIVATE_REPLY = "Priya\nNothing to show here.\nPrivate notes are only on your computer."


def dm(user_id="111"):
    return SimpleNamespace(user_id=user_id, chat_type="dm", is_bot=False)


@pytest.fixture
def seeded(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    handle = mod("commands").handle
    for line in ("save Priya likes tea", "save --private Priya sees a therapist on Tuesdays", "save Priya plays tennis on Tuesdays"):
        handle(line, platform="cli", vault=vault)
    return vault


@pytest.fixture
def phone(seeded, mod):
    return lambda text, **kw: mod("commands").handle(text, platform="telegram", source=dm(), vault=seeded, **kw)


@pytest.fixture
def desk(seeded, mod):
    return lambda text: mod("commands").handle(text, platform="cli", vault=seeded)


def test_saving_private_replies_normally(mod, seeded):
    assert mod("commands").handle("save --private Priya likes secrets", platform="cli", vault=seeded) == "Saved to Priya."


def test_terminal_sees_private_line(desk):
    assert "therapist" in desk("priya") and "therapist" in desk("priya therapist")


def test_desktop_surface_sees_private_line(seeded, mod):
    assert "therapist" in mod("commands").handle("priya therapist", platform="desktop", vault=seeded)


def test_desktop_page_shows_and_marks_private(seeded, mod):
    lines = mod("desktop_service").card_detail(1, seeded)["lines"]
    assert [line["private"] for line in lines] == [False, True, False]


def test_messaging_private_match_and_no_match_are_identical(phone):
    matching_private = phone("priya therapist")
    matching_nothing = phone("priya shoe size")
    assert matching_private == matching_nothing == PRIVATE_REPLY
    assert "therapist" not in matching_private


def test_messaging_public_answer_never_mentions_private(phone):
    reply = phone("priya tuesdays")
    assert "plays tennis on Tuesdays" in reply and "therapist" not in reply and "rivate" not in reply


def test_card_without_private_says_nothing_saved(mod, seeded):
    handle = mod("commands").handle
    handle("save Marco likes jazz", platform="cli", vault=seeded)
    assert handle("marco shoe size", platform="telegram", source=dm(), vault=seeded) == "Nothing saved about that."


def test_card_view_counts_private_notes(phone):
    assert phone("priya").split("\n")[-1] == "1 private note · on your computer"


def test_card_view_counts_several_private_notes(mod, seeded, phone):
    mod("commands").handle("save --private Priya second secret", platform="cli", vault=seeded)
    assert phone("priya").split("\n")[-1] == "2 private notes · on your computer"
    assert "second secret" not in phone("priya")


def test_card_view_has_no_private_line_without_private_notes(mod, seeded):
    handle = mod("commands").handle
    handle("save Marco likes jazz", platform="cli", vault=seeded)
    assert "rivate" not in handle("marco", platform="telegram", source=dm(), vault=seeded)


def test_terminal_card_has_no_private_count_line(desk):
    assert "on your computer" not in desk("priya")


def test_old_wording_is_gone():
    from pathlib import Path

    root = Path(__file__).parent.parent
    assert not any("See it on your computer" in path.read_text() for path in root.glob("*.py"))


def test_messaging_public_match_is_normal(phone):
    assert phone("priya tea") == "Priya\n**likes tea**\ntoday · terminal"


def test_messaging_card_view_omits_private_lines(phone):
    view = phone("priya")
    assert "therapist" not in view and "plays tennis" in view


def test_messaging_history_omits_private(phone):
    assert "therapist" not in phone("history priya")


def test_messaging_correct_cannot_reach_private_line(phone, desk):
    assert phone("correct Priya 2 plays golf") == "Saved to Priya."
    assert "therapist" in desk("priya") and "plays golf" in desk("priya")


def test_correcting_private_keeps_it_private(desk, phone):
    desk("correct Priya 2 sees a doctor on Tuesdays")
    assert phone("priya doctor") == PRIVATE_REPLY


SHARED = {"shared": ["telegram:222:read"]}


def shared_ask(mod, seeded, text):
    return mod("commands").handle(text, platform="telegram", source=dm("222"), vault=seeded, **SHARED)


def test_shared_person_gets_nothing_saved(seeded, mod):
    assert shared_ask(mod, seeded, "priya therapist") == "Nothing saved about that."
    assert shared_ask(mod, seeded, "priya shoe size") == "Nothing saved about that."


def test_shared_person_sees_no_hidden_count(seeded, mod):
    view = shared_ask(mod, seeded, "priya")
    assert "hidden" not in view and "rivate" not in view and "computer" not in view and "therapist" not in view


def test_shared_person_on_a_card_of_only_hidden_notes(seeded, mod):
    mod("commands").handle("save --new --private Quentin only secret", platform="cli", vault=seeded)
    assert shared_ask(mod, seeded, "quentin") == "Quentin\nNo lines saved yet."


def test_ai_tool_never_returns_private(seeded, mod):
    reply = json.loads(mod("ai_tool").handle({"action": "lookup", "question": "priya therapist"}, vault=seeded, session=("cli", None)))
    assert reply["status"] == "nothing" and "therapist" not in json.dumps(reply)


def test_ai_tool_public_only_on_shared_word(seeded, mod):
    reply = json.loads(mod("ai_tool").handle({"action": "lookup", "question": "priya tuesdays"}, vault=seeded, session=("cli", None)))
    assert [m["saved_words"] for m in reply["matches"]] == ["plays tennis on Tuesdays"]


def test_choice_hint_never_shows_private_line(seeded, mod):
    handle = mod("commands").handle
    handle('save --private "Sam Lee" sees a therapist', platform="cli", vault=seeded)
    handle('save "Sam Ong" likes jazz', platform="cli", vault=seeded)
    reply = handle("sam", platform="telegram", source=dm(), vault=seeded)
    assert reply.startswith("More than one match.") and "therapist" not in reply


def test_private_flag_with_new_flag(desk):
    assert desk("save --private --new Quentin likes chess").startswith("New card for Quentin. Saved.")


def test_undo_private_save(desk):
    desk("save --private Priya likes secrets")
    desk("undo")
    assert "likes secrets" not in desk("priya")


def test_old_store_is_updated_on_open(tmp_path, mod):
    import sqlite3

    vault_module, db = mod("vault"), mod("db")
    instance = vault_module.Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    instance.setup()
    with instance.write() as connection:
        connection.execute("ALTER TABLE details DROP COLUMN private")
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO settings(key,value) VALUES('old','store')")
    with instance.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
        assert "private" in [row[1] for row in connection.execute("PRAGMA table_info(details)")]
        assert isinstance(connection, sqlite3.Connection)


def test_future_store_is_refused(tmp_path, mod):
    instance = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    instance.setup()
    with instance.write() as connection:
        connection.execute("INSERT INTO settings(key,value) VALUES('a','b')")
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(mod("vault").Refused):
        with instance.read():
            pass
