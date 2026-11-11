"""Delete a person or a line: gone from everything, kept for history, and Undo brings it back."""
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def run(vault, mod):
    def run(text, answer=None, platform="desktop"):
        return mod("commands").handle(text, platform=platform, vault=vault, ask=lambda _q, _c: answer)

    return run


def live_names(vault):
    with vault.read() as connection:
        return sorted(row[0] for row in connection.execute("SELECT name FROM cards WHERE closed_at IS NULL"))


def card_id(vault, name):
    with vault.read() as connection:
        return connection.execute("SELECT id FROM cards WHERE name=?", (name,)).fetchone()[0]


# Store upgrade.

def test_v2_store_is_upgraded_with_its_data_unchanged(tmp_path, mod):
    vault = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    vault.setup()
    mod("commands").handle('save "Sis Nel" lives on Elm Street', platform="cli", vault=vault)
    mod("commands").handle("link Priya sister \"Sis Nel\"", platform="cli", vault=vault)
    with vault.write() as connection:
        connection.execute("ALTER TABLE cards DROP COLUMN closed_at")  # the v2 shape
        connection.execute("PRAGMA user_version=2")
        before = {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")] for table in ("cards", "details", "links", "aliases", "changes")}
    with vault.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3 == mod("db").SCHEMA_VERSION
        after = {table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")] for table in before}
    assert [row[:-1] for row in after["cards"]] == before["cards"] and all(row[-1] is None for row in after["cards"])
    assert {t: after[t] for t in ("details", "links", "aliases", "changes")} == {t: before[t] for t in ("details", "links", "aliases", "changes")}


# Delete a person in chat.

def test_delete_then_undo(run, vault):
    run('save "Sis Nel" lives on Elm Street')
    assert run('delete Sis Nel') == "Deleted Sis Nel. Undo: /myfolks undo"
    assert live_names(vault) == []
    assert run("undo") == "Undone: deleted Sis Nel."
    assert live_names(vault) == ["Sis Nel"]
    assert "lives on Elm Street" in run("sis nel")


def test_delete_keeps_every_row(run, vault):
    run('save "Sis Nel" lives on Elm Street')
    run("link Priya sister \"Sis Nel\"")
    run("delete Sis Nel")
    with vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM details WHERE closed_at IS NULL").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM links WHERE closed_at IS NULL").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM aliases").fetchone()[0] >= 1


def test_deleted_person_is_gone_from_every_read(run, vault, mod):
    run('save "Sis Nel" phone 555 0100')
    run("save Priya likes tea")
    run("link Priya sister \"Sis Nel\"")
    deleted_id = card_id(vault, "Sis Nel")
    run("delete Sis Nel")
    assert run("sis nel") == "Nothing saved about that."
    assert run("nel") == "No one called nel yet."
    assert run("priya") == "Priya\nlikes tea\n1 note · last saved today\nChange a line: /myfolks fix Priya    Delete: /myfolks forget Priya"  # the link to a deleted person is left out
    assert run("priya sister") == "Nothing saved about that."
    assert run(f"#{deleted_id}") == "Nothing saved about that."
    assert run("sis nell") == "Nothing saved about that."  # no "Did you mean" for a deleted person
    assert run("").startswith("MyFolks: 1 card.")
    service = mod("desktop_service")
    assert [c["name"] for c in service.find("", vault=vault)["cards"]] == ["Priya"]
    assert service.find("nel", vault=vault)["cards"] == []
    assert service.card_detail(deleted_id, vault=vault) == {"state": "missing"}
    assert [link for link in service.card_detail(card_id(vault, "Priya"), vault=vault)["links"]] == []
    assert service.status(vault=vault)["cards"] == 1
    reply = json.loads(mod("ai_tool").handle({"action": "lookup", "question": "sis nel phone"}, vault=vault, session=("cli", None)))
    assert reply["status"] != "found"
    with vault.read() as connection:
        exported = mod("backup").export_document(connection)
    assert [card["name"] for card in exported["cards"]] == ["Priya"]


def test_saving_to_a_deleted_name_is_an_unknown_name(run, vault):
    run('save "Sis Nel" lives on Elm Street')
    run("delete Sis Nel")
    assert run('save "Sis Nel" likes figs') == "New card for Sis Nel. Saved. Undo: /myfolks undo"
    assert live_names(vault) == ["Sis Nel"]
    with vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM cards WHERE name='Sis Nel'").fetchone()[0] == 2


def test_close_name_asks_first(run, vault):
    run("save Rositah likes tea")
    assert run("delete Rositha", answer="cancel") == "Nothing was changed."
    assert live_names(vault) == ["Rositah"]
    assert run("delete Rositha", answer=str(card_id(vault, "Rositah"))).startswith("Deleted Rositah")


def test_close_name_on_telegram_gives_the_commands(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    mod("commands").handle("save Rositah likes tea", platform="cli", vault=vault)
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    reply = mod("commands").handle("delete Rositha", platform="telegram", source=source, vault=vault)
    assert reply == "Did you mean Rositah?\nNothing was deleted. To go ahead, send one of these:\n/myfolks delete Rositah"
    assert live_names(vault) == ["Rositah"]


def test_unknown_name_and_usage(run):
    assert run("delete Zed") == "No one called Zed yet."
    assert run("delete") == "To delete someone: /myfolks delete <name>    One line: /myfolks delete <name> <line number>"


def test_shared_people_and_the_ai_can_never_delete(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111", "222"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    source = SimpleNamespace(user_id="222", chat_type="dm", is_bot=False)
    assert mod("commands").handle("delete Priya", platform="telegram", source=source, vault=vault, shared="telegram:222:add") == "MyFolks isn't available here."
    reply = json.loads(mod("ai_tool").handle({"action": "delete", "name": "Priya"}, vault=vault, session=("cli", None)))
    assert reply["status"] not in ("saved", "deleted")
    assert live_names(vault) == ["Priya"]


# Import and Google sync never bring a deleted person back.

def _import(vault, mod, *contacts):
    importer = mod("importer")
    return importer.import_in_batches(vault, [importer.Incoming(**c) for c in contacts], "test import").summary


def test_import_skips_a_deleted_person_by_phone_email_or_name(run, vault, mod):
    run('save "Sis Nel" phone 555 0100')
    run('save Bo email bo@example.com')
    run('save Cy likes tea')
    for name in ("Sis Nel", "Bo", "Cy"):
        run(f'delete {name}')
    summary = _import(vault, mod, {"name": "Nelly S", "phones": ["555 0100"]}, {"name": "Robert", "emails": ["bo@example.com"]}, {"name": "Cy"}, {"name": "Dee"})
    assert (summary.skipped, summary.new) == (3, 1)
    assert live_names(vault) == ["Dee"]


def test_review_never_offers_a_deleted_person(run, vault, mod):
    run('save "Mel Ortiz" likes tea')
    _import(vault, mod, {"name": "Mel Ortiz", "phones": ["555 0103"]})
    run('delete Mel Ortiz')
    assert mod("commands").handle("review", platform="cli", vault=vault).splitlines()[1] == "1. Mel Ortiz [phone 555 0103] could be: "
    items = mod("desktop_service").review_list(vault=vault)["items"]
    assert items and items[0]["candidates"] == []


# Desktop.

def test_desktop_delete_person_and_undo(run, vault, mod):
    run('save "Sis Nel" lives on Elm Street')
    service = mod("desktop_service")
    result = service.delete_person(card_id(vault, "Sis Nel"), vault=vault)
    assert result["state"] == "ready" and isinstance(result["change_id"], int) and result["name"] == "Sis Nel"
    assert live_names(vault) == []
    assert service.delete_person(card_id(vault, "Sis Nel"), vault=vault) == {"state": "missing"}
    assert run("undo") == "Undone: deleted Sis Nel."
    assert live_names(vault) == ["Sis Nel"]


def test_desktop_copy_for_delete():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    for line in ("deletePerson: 'Delete person',", "deletePersonTitle: name => `Delete ${name}?`,",
                 "deletePersonBody: 'They disappear from MyFolks. Their details stay in history, and Undo brings them back.',",
                 "delete: 'Delete',", "cancel: 'Cancel',"):
        assert line in js
    assert "jsx(ConfirmDialog, {" in js and "destructive: true" in js


def test_google_sync_never_brings_a_deleted_person_back(run, vault, monkeypatch, mod):
    import sys
    import types

    from test_google_sync import FakeHermes, ProviderNotSignedIn, person

    fake = FakeHermes()
    helper = types.ModuleType("hermes_cli.plugin_provider_requests")
    helper.ProviderNotSignedIn, helper.credentialed_provider_request = ProviderNotSignedIn, fake
    if "hermes_cli" not in sys.modules:
        monkeypatch.setitem(sys.modules, "hermes_cli", types.ModuleType("hermes_cli"))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_provider_requests", helper)
    fake.people = [person("Sis Nel", "555 0100"), person("Dee", "555 0104")]
    run("sync")
    run("delete Sis Nel")
    assert run("sync") == "Google contacts synced: nothing new."
    assert live_names(vault) == ["Dee"]


# 2. Delete one line.

def test_delete_one_line_then_undo(run, vault):
    run("save Priya likes tea")
    run("save Priya allergic to peanuts")
    assert run("delete Priya 2") == "Deleted line 2 from Priya. Undo: /myfolks undo"
    assert "peanuts" not in run("priya")
    assert run("correct Priya").splitlines()[1:2] == ["1. likes tea"]
    history = run("history priya")
    assert "allergic to peanuts" in history and ", deleted " in history and ", replaced " not in history
    assert run("undo") == "Undone: deleted a line on Priya."
    assert "allergic to peanuts" in run("priya allergic")


def test_corrected_line_still_reads_replaced_in_history(run):
    run("save Priya likes tea")
    run("correct Priya 1 likes green tea")
    history = run("history priya")
    assert ", replaced " in history and ", deleted " not in history


def test_delete_line_number_out_of_range(run, vault):
    run("save Priya likes tea")
    assert run("delete Priya 5") == "That line number isn't on the card."
    assert "likes tea" in run("priya")


def test_name_ending_in_a_number_is_still_a_name(run, vault):
    run('save "Studio 54" opens at nine')
    assert run("delete Studio 54") == "Deleted Studio 54. Undo: /myfolks undo"


def test_telegram_line_numbers_match_correct(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    handle = mod("commands").handle
    handle("save Priya secret code 1234", platform="cli", vault=vault)
    handle("hide Priya 1", platform="cli", vault=vault)
    handle("save Priya likes tea", platform="cli", vault=vault)
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    phone = lambda text: handle(text, platform="telegram", source=source, vault=vault)  # noqa: E731
    assert phone("correct Priya").splitlines()[1] == "1. likes tea"
    assert phone("delete Priya 1") == "Deleted line 1 from Priya. Undo: /myfolks undo"
    with vault.read() as connection:
        open_texts = [row[0] for row in connection.execute("SELECT text FROM details WHERE closed_at IS NULL")]
    assert open_texts == ["secret code 1234"]


def test_desktop_delete_line_and_undo(run, vault, mod):
    run("save Priya likes tea")
    service = mod("desktop_service")
    line_id = service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"][0]["id"]
    result = service.delete_line(line_id, vault=vault)
    assert result["state"] == "ready" and isinstance(result["change_id"], int)
    assert service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"] == []
    assert service.delete_line(line_id, vault=vault) == {"state": "missing"}
    assert run("undo") == "Undone: deleted a line on Priya."
    assert len(service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"]) == 1


def test_desktop_line_delete_button():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    assert "deleteLine: 'Delete'," in js and "`/lines/${line.id}/delete`" in js


# 3. Undo that can't undo the wrong thing.

def test_toast_undo_undoes_exactly_its_change(run, vault, mod):
    run('save "Sis Nel" lives on Elm Street')
    service = mod("desktop_service")
    deleted = service.delete_person(card_id(vault, "Sis Nel"), vault=vault)
    assert service.undo(deleted["change_id"], vault=vault) == {"state": "ready", "message": "Undone: deleted Sis Nel."}
    assert live_names(vault) == ["Sis Nel"]


def test_toast_undo_refuses_after_a_telegram_save_in_between(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    handle = mod("commands").handle
    handle('save "Sis Nel" lives on Elm Street', platform="cli", vault=vault)
    service = mod("desktop_service")
    deleted = service.delete_person(card_id(vault, "Sis Nel"), vault=vault)
    source = SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)
    assert handle("save Priya likes tea", platform="telegram", source=source, vault=vault) == "New card for Priya. Saved. Undo: /myfolks undo"
    assert service.undo(deleted["change_id"], vault=vault) == {"state": "changed", "message": "Can't undo that: something changed since. See History."}
    assert live_names(vault) == ["Priya"]  # Priya's save stays, and Sis Nel stays deleted


def test_toast_undo_refuses_twice_and_an_unknown_id(run, vault, mod):
    run("save Priya likes tea")
    service = mod("desktop_service")
    line_id = service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"][0]["id"]
    deleted = service.delete_line(line_id, vault=vault)
    assert service.undo(deleted["change_id"], vault=vault)["state"] == "ready"
    assert service.undo(deleted["change_id"], vault=vault)["state"] == "changed"
    assert service.undo(999999, vault=vault)["state"] == "changed"
    assert live_names(vault) == ["Priya"] and len(service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"]) == 1


def test_chat_help_names_undo_plainly(run):
    run("save Priya likes tea")
    assert run("").splitlines()[-1] == "Undo your last change: /myfolks undo"


def test_desktop_toast_wiring():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    assert "deletedPersonToast: name => `Deleted ${name}.`," in js and "undo: 'Undo'," in js
    assert ".rest('/undo', { body: { change_id: changeId }, method: 'POST' })" in js
    assert "host.notify({" in js


# 4. Edit a line in Desktop.

def test_desktop_edit_line_keeps_the_old_text_in_history_and_undoes(run, vault, mod):
    run("save Priya likes tea")
    service = mod("desktop_service")
    line_id = service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"][0]["id"]
    result = service.edit_line(line_id, "likes green tea", vault=vault)
    assert result["state"] == "ready" and isinstance(result["change_id"], int)
    assert [line["text"] for line in service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"]] == ["likes green tea"]
    history = run("history priya")
    assert "likes tea" in history and ", replaced " in history
    assert service.undo(result["change_id"], vault=vault)["state"] == "ready"
    assert [line["text"] for line in service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"]] == ["likes tea"]


def test_desktop_edit_line_refuses_empty_unchanged_and_closed(run, vault, mod):
    run("save Priya likes tea")
    service = mod("desktop_service")
    line_id = service.card_detail(card_id(vault, "Priya"), vault=vault)["lines"][0]["id"]
    assert service.edit_line(line_id, "  ", vault=vault) == {"state": "invalid"}
    assert service.edit_line(line_id, "x" * 2001, vault=vault) == {"state": "invalid"}
    assert service.edit_line(line_id, "likes tea", vault=vault) == {"state": "unchanged"}
    service.edit_line(line_id, "likes coffee", vault=vault)
    assert service.edit_line(line_id, "again", vault=vault) == {"state": "missing"}  # the old line is closed


def test_desktop_edit_wiring():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    assert "editLine: 'Edit'," in js and "savedToast: 'Saved.'," in js and "`/lines/${line.id}/edit`" in js


# 5. New person in Desktop.

def test_desktop_new_person_adds_and_undoes(run, vault, mod):
    service = mod("desktop_service")
    result = service.new_person("Sis Nel", "lives on Elm Street", vault=vault)
    assert result["state"] == "ready" and result["card"]["name"] == "Sis Nel" and isinstance(result["change_id"], int)
    assert "lives on Elm Street" in run("sis nel")
    assert service.undo(result["change_id"], vault=vault) == {"state": "ready", "message": "Undone: added Sis Nel."}
    assert live_names(vault) == []


def test_desktop_new_person_exact_name_opens_that_person(run, vault, mod):
    run("save Priya likes tea")
    result = mod("desktop_service").new_person("priya", "", vault=vault)
    assert result == {"state": "exists", "card": {"id": card_id(vault, "Priya"), "name": "Priya", "kind": "person"}}
    assert live_names(vault) == ["Priya"]


def test_desktop_new_person_close_name_asks_then_follows_the_choice(run, vault, mod):
    run("save Rositah likes tea")
    service = mod("desktop_service")
    asked = service.new_person("Rositha", "", vault=vault)
    assert asked["state"] == "close" and [card["name"] for card in asked["names"]] == ["Rositah"]
    assert live_names(vault) == ["Rositah"]
    assert service.new_person("Rositha", "", choice=str(card_id(vault, "Rositah")), vault=vault)["state"] == "exists"
    assert service.new_person("Rositha", "", choice="new", vault=vault)["state"] == "ready"
    assert live_names(vault) == ["Rositah", "Rositha"]


def test_desktop_new_person_refuses_empty_and_detail_words(vault, mod):
    service = mod("desktop_service")
    assert service.new_person("  ", "", vault=vault) == {"state": "invalid"}
    assert service.new_person("Address", "Elm Street", vault=vault) == {"state": "detail_word"}
    assert live_names(vault) == []


def test_desktop_new_person_wiring():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    assert "newPerson: 'New person'," in js and "addedToast: name => `Added ${name}.`," in js
    assert ".rest('/people', {" in js and "jsx(NewPerson, {" in js


# 6. Rename a person in Desktop.

def test_desktop_rename_keeps_the_old_name_findable_and_undoes(run, vault, mod):
    run("save Nel lives on Elm Street")
    service = mod("desktop_service")
    nel = card_id(vault, "Nel")
    result = service.rename_person(nel, "Sis Nel", vault=vault)
    assert result["state"] == "ready" and result["card"]["name"] == "Sis Nel"
    assert live_names(vault) == ["Sis Nel"]
    assert run("nel").startswith("Sis Nel\n")  # the old name still finds her
    assert run("sis nel").startswith("Sis Nel\n")
    assert service.undo(result["change_id"], vault=vault) == {"state": "ready", "message": "Undone: renamed Nel to Sis Nel."}
    assert live_names(vault) == ["Nel"]
    with vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM aliases WHERE card_id=?", (nel,)).fetchone()[0] == 0


def test_desktop_rename_refuses_a_name_someone_else_has(run, vault, mod):
    run("save Priya likes tea")
    run("save Nel likes figs")
    service = mod("desktop_service")
    assert service.rename_person(card_id(vault, "Nel"), "priya", vault=vault) == {"state": "taken", "name": "priya"}
    assert service.rename_person(card_id(vault, "Nel"), "Nel", vault=vault) == {"state": "unchanged"}
    assert service.rename_person(card_id(vault, "Nel"), "", vault=vault) == {"state": "invalid"}
    assert service.rename_person(card_id(vault, "Nel"), "phone", vault=vault) == {"state": "detail_word"}
    assert live_names(vault) == ["Nel", "Priya"]


def test_desktop_rename_to_a_deleted_persons_name_is_allowed(run, vault, mod):
    run("save Priya likes tea")
    run("save Nel likes figs")
    run("delete Priya")
    assert mod("desktop_service").rename_person(card_id(vault, "Nel"), "Priya", vault=vault)["state"] == "ready"


def test_desktop_rename_wiring():
    from pathlib import Path

    js = (Path(__file__).parent.parent / "desktop" / "plugin.js").read_text()
    assert "rename: 'Rename'," in js and "renamedToast: 'Renamed.'," in js
    assert "nameTaken: name => `Someone called ${name} is already here.`," in js and "`/cards/${card.id}/rename`" in js
