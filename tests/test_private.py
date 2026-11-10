import json
from types import SimpleNamespace

import pytest

PRIVATE_REPLY = "Private. See it on your computer."


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


def test_messaging_says_only_private(phone):
    assert phone("priya therapist") == PRIVATE_REPLY


def test_messaging_private_match_hides_public_matches_too(phone):
    assert phone("priya tuesdays") == PRIVATE_REPLY


def test_messaging_public_match_is_normal(phone):
    assert 'Priya: "likes tea"' in phone("priya tea")


def test_messaging_card_view_omits_private_and_renumbers(phone):
    view = phone("priya")
    assert "therapist" not in view and view.split("\n")[2].startswith("2. plays tennis")


def test_messaging_history_omits_private(phone):
    assert "therapist" not in phone("history priya")


def test_messaging_correct_cannot_reach_private_line(phone, desk):
    assert phone("correct Priya 2 plays golf") == "Saved to Priya."
    assert "therapist" in desk("priya") and "plays golf" in desk("priya")


def test_correcting_private_keeps_it_private(desk, phone):
    desk("correct Priya 2 sees a doctor on Tuesdays")
    assert phone("priya doctor") == PRIVATE_REPLY


def test_shared_person_gets_private_reply(seeded, mod):
    reply = mod("commands").handle("priya therapist", platform="telegram", source=dm("222"), vault=seeded, shared=["telegram:222:read"])
    assert reply == PRIVATE_REPLY


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
