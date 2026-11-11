from loader import save_hidden
import json
from types import SimpleNamespace

import pytest

PRIVATE_REPLY = "Priya\nNothing to show here.\nSome notes are hidden from chat."


def dm(user_id="111"):
    return SimpleNamespace(user_id=user_id, chat_type="dm", is_bot=False)


@pytest.fixture
def seeded(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    save_hidden(vault, "Priya sees a therapist on Tuesdays")
    handle("save Priya plays tennis on Tuesdays", platform="cli", vault=vault)
    return vault


@pytest.fixture
def phone(seeded, mod):
    return lambda text, **kw: mod("commands").handle(text, platform="telegram", source=dm(), vault=seeded, **kw)


@pytest.fixture
def desk(seeded, mod):
    return lambda text: mod("commands").handle(text, platform="cli", vault=seeded)


@pytest.mark.parametrize("flag", ["--private", "--computer-only", "--PRIVATE"])
@pytest.mark.parametrize("place", ["save {flag} Priya likes secrets", "save Priya {flag} likes secrets", "save --new {flag} Zed x"])
@pytest.mark.parametrize("platform", ["cli", "telegram"])
def test_old_flags_save_nothing(mod, seeded, flag, place, platform):
    before = seeded.store_path.read_bytes()
    source = dm() if platform == "telegram" else None
    assert mod("commands").handle(place.format(flag=flag), platform=platform, source=source, vault=seeded) == "To hide a note from chat, use your computer."
    assert seeded.store_path.read_bytes() == before


def test_every_note_saves_normally_from_chat(mod, seeded, phone):
    assert phone("save Priya likes figs") == "Saved to Priya. Undo: /myfolks undo"
    assert "likes figs" in phone("priya figs")


def test_quoted_flag_words_are_ordinary_text(desk):
    assert desk('save Priya "--private" is a word she uses') == "Saved to Priya. Undo: /myfolks undo"


@pytest.mark.parametrize("command", ["hide Priya 1", "unhide Priya 2", "hide Priya"])
def test_hide_in_chat_saves_nothing(phone, seeded, command):
    before = seeded.store_path.read_bytes()
    assert phone(command) == "To hide a note from chat, use your computer."
    assert seeded.store_path.read_bytes() == before


def test_hide_refused_for_shared_people(seeded, mod):
    assert mod("commands").handle("hide Priya 1", platform="telegram", source=dm("222"), vault=seeded, shared=["telegram:222:add"]) == "MyFolks isn't available here."


def test_terminal_hide_and_unhide(desk, phone):
    assert desk("hide Priya 1") == "Hidden from chat."
    assert "likes tea" not in phone("priya")
    assert "likes tea" in desk("priya")
    assert desk("unhide Priya 1") == "Showing in chat again."
    assert "likes tea" in phone("priya")


def test_hide_with_name_alone_lists_numbered_lines(desk):
    lines = desk("hide Priya").split("\n")
    assert lines[:4] == ["Priya", "1. likes tea", "2. sees a therapist on Tuesdays · hidden from chat", "3. plays tennis on Tuesdays"]


def test_hide_can_be_undone(desk, phone):
    desk("hide Priya 1")
    assert desk("undo").startswith("Undone:")
    assert "likes tea" in phone("priya")


def test_hide_bad_line_and_repeat(desk):
    assert desk("hide Priya 9") == "That line number isn't on the card."
    assert desk("hide Priya 2") == "That line is already hidden from chat."
    assert desk("unhide Priya 1") == "That line is already showing in chat."


def test_hide_near_name_asks_with_no_details(desk):
    reply = desk("hide Prya")
    assert reply.startswith("Did you mean Priya?") and "tea" not in reply


def test_desktop_control_can_be_undone(seeded, mod, phone):
    service = mod("desktop_service")
    line = service.card_detail(1, seeded)["lines"][0]
    assert service.set_hidden(line["id"], True, seeded) == {"state": "ready"}
    assert service.card_detail(1, seeded)["lines"][0]["private"] is True and "likes tea" not in phone("priya")
    assert service.set_hidden(line["id"], False, seeded) == {"state": "ready"}
    assert "likes tea" in phone("priya")


def test_desktop_hide_is_undoable_with_undo(seeded, mod, phone):
    service = mod("desktop_service")
    service.set_hidden(service.card_detail(1, seeded)["lines"][0]["id"], True, seeded)
    mod("commands").handle("undo", platform="cli", vault=seeded)
    assert "likes tea" in phone("priya")


def test_desktop_missing_line(seeded, mod):
    assert mod("desktop_service").set_hidden(999, True, seeded) == {"state": "missing"}


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
    assert handle("marco shoe size", platform="telegram", source=dm(), vault=seeded) == "Nothing saved about that.\nNot sure what to send? /myfolks help"


def test_card_view_counts_private_notes(phone):
    assert phone("priya").split("\n")[-2] == "1 hidden from chat"


def test_card_view_counts_several_private_notes(mod, seeded, phone):
    save_hidden(seeded, "Priya second secret")
    assert phone("priya").split("\n")[-2] == "2 hidden from chat"
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
    assert phone("correct Priya 2 plays golf") == "Changed. Undo: /myfolks undo"
    assert "therapist" in desk("priya") and "plays golf" in desk("priya")


def test_correcting_private_keeps_it_private(desk, phone):
    desk("correct Priya 2 sees a doctor on Tuesdays")
    assert phone("priya doctor") == PRIVATE_REPLY


SHARED = {"shared": ["telegram:222:read"]}


def shared_ask(mod, seeded, text):
    return mod("commands").handle(text, platform="telegram", source=dm("222"), vault=seeded, **SHARED)


def test_shared_person_gets_nothing_saved(seeded, mod):
    assert shared_ask(mod, seeded, "priya therapist") == "Nothing saved about that.\nNot sure what to send? /myfolks help"
    assert shared_ask(mod, seeded, "priya shoe size") == "Nothing saved about that.\nNot sure what to send? /myfolks help"


def test_shared_person_sees_no_hidden_count(seeded, mod):
    view = shared_ask(mod, seeded, "priya")
    assert "hidden" not in view and "rivate" not in view and "computer" not in view and "therapist" not in view


def test_shared_person_on_a_card_of_only_hidden_notes(seeded, mod):
    save_hidden(seeded, "--new Quentin only secret")
    assert shared_ask(mod, seeded, "quentin") == "Quentin\nNo lines saved yet."


def test_ai_tool_never_returns_private(seeded, mod):
    reply = json.loads(mod("ai_tool").handle({"action": "lookup", "question": "priya therapist"}, vault=seeded, session=("cli", None)))
    assert reply["status"] == "nothing" and "therapist" not in json.dumps(reply)


def test_ai_tool_public_only_on_shared_word(seeded, mod):
    reply = json.loads(mod("ai_tool").handle({"action": "lookup", "question": "priya tuesdays"}, vault=seeded, session=("cli", None)))
    assert [m["saved_words"] for m in reply["matches"]] == ["plays tennis on Tuesdays"]


def test_choice_hint_never_shows_private_line(seeded, mod):
    handle = mod("commands").handle
    save_hidden(seeded, '"Sam Lee" sees a therapist')
    handle('save "Sam Ong" likes jazz', platform="cli", vault=seeded)
    reply = handle("sam", platform="telegram", source=dm(), vault=seeded)
    assert reply.startswith("More than one match.") and "therapist" not in reply


def test_new_flag_still_works(desk):
    assert desk("save --new Quentin likes chess").startswith("New card for Quentin. Saved. Undo: /myfolks undo")


def test_undo_private_save(desk, seeded):
    save_hidden(seeded, "Priya likes secrets")
    desk("undo")
    desk("undo")
    assert "likes secrets" not in desk("priya")


def test_old_store_is_updated_on_open(tmp_path, mod):
    import sqlite3

    vault_module, db = mod("vault"), mod("db")
    instance = vault_module.Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    instance.setup()
    with instance.write() as connection:
        connection.execute("ALTER TABLE details DROP COLUMN private")
        connection.execute("ALTER TABLE cards DROP COLUMN closed_at")  # a real v1 store had neither
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


def test_terminal_card_marks_hidden_lines(desk):
    assert desk("priya").split("\n")[1:4] == ["likes tea", "sees a therapist on Tuesdays · hidden from chat", "plays tennis on Tuesdays"]


def test_hidden_label_only_in_the_terminal(seeded, mod, phone):
    assert "· hidden from chat" not in mod("commands").handle("priya", platform="desktop", vault=seeded)
    assert "· hidden from chat" not in phone("priya")
    assert "· hidden from chat" not in phone("history priya")


def test_terminal_answer_lines_are_unlabelled(desk):
    assert "· hidden from chat" not in desk("priya therapist")
