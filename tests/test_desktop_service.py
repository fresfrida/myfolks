import pytest


@pytest.fixture
def service(mod):
    return mod("desktop_service")


@pytest.fixture
def loaded(vault, mod):
    handle = mod("commands").handle
    for line in ("save Priya is allergic to peanuts", "save Biscuit birthday March 3", "link Priya dog Biscuit"):
        handle(line, platform="cli", vault=vault)
    return vault


def test_status_ready_counts(loaded, service):
    assert service.status(loaded) == {"state": "ready", "cards": 2, "review": 0}


def test_find_browses_everyone_with_no_query(loaded, service):
    assert [card["name"] for card in service.find("", loaded)["cards"]] == ["Biscuit", "Priya"]


def test_find_filters_by_name(loaded, service):
    assert [card["name"] for card in service.find("bisc", loaded)["cards"]] == ["Biscuit"]


def test_find_direct_answer_is_receipt(loaded, service):
    answer = service.find("priya alergic", loaded)["answer"]
    assert answer["kind"] == "direct" and answer["lines"][0]["text"] == "is allergic to peanuts"
    assert answer["lines"][0]["receipt"].startswith("Saved ") and answer["lines"][0]["receipt"].endswith(" from terminal")


def test_find_follows_links(loaded, service):
    answer = service.find("priya dog birthday", loaded)["answer"]
    assert answer["card"]["name"] == "Biscuit" and answer["lines"][0]["text"] == "birthday March 3"


def test_find_unsure_is_related(loaded, service, mod):
    mod("commands").handle("save Marco owes me money", platform="cli", vault=loaded)
    assert service.find("marco debt", loaded)["answer"]["kind"] == "related"


def test_find_nothing(loaded, service):
    assert service.find("priya shoe size", loaded)["answer"]["kind"] == "nothing"
    assert service.find("nobody here", loaded)["answer"]["kind"] == "nothing"


def test_find_typo_is_announced(loaded, service):
    answer = service.find("prya allergic", loaded)["answer"]
    assert answer["corrected"] is True and answer["card"]["name"] == "Priya"


def test_find_same_name_offers_choices(vault, service, mod):
    handle = mod("commands").handle
    handle('save "Sam Lee" likes tea', platform="cli", vault=vault)
    handle('save "Sam Ong" likes jazz', platform="cli", vault=vault)
    assert len(service.find("sam", vault)["answer"]["choices"]) == 2


def test_card_detail_has_numbered_lines_and_links_both_ways(loaded, service):
    detail = service.card_detail(1, loaded)
    assert detail["lines"][0]["number"] == 1
    assert detail["links"][0] == {"relation": "dog", "outgoing": True, "id": 2, "name": "Biscuit"}
    assert service.card_detail(2, loaded)["links"][0]["outgoing"] is False


def test_card_missing(loaded, service):
    assert service.card_detail(99, loaded) == {"state": "missing"}


def test_save_line_uses_desktop_source(loaded, service):
    assert service.save_line(1, "likes tea", loaded)["message"] == "Saved to Priya."
    assert service.card_detail(1, loaded)["lines"][1]["receipt"].endswith(" from Desktop")


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001])
def test_save_line_rejects_bad_text(loaded, service, text):
    assert service.save_line(1, text, loaded) == {"state": "invalid"}


def test_save_line_is_undoable_from_contacts(loaded, service, mod):
    service.save_line(1, "likes tea", loaded)
    mod("commands").handle("undo", platform="cli", vault=loaded)
    assert len(service.card_detail(1, loaded)["lines"]) == 1


def test_review_merge_and_keep(vault, service, mod):
    importer = mod("importer")
    mod("commands").handle('save "Noor Hasan" likes tea', platform="cli", vault=vault)
    contacts = [importer.Incoming(name="Noor Hassan", details=["likes jazz"]), importer.Incoming(name="Noor Hasann", details=["likes rain"])]
    with vault.write() as connection:
        importer.apply_contacts(connection, contacts, "test import")
    items = service.review_list(vault)["items"]
    assert len(items) == 2 and items[0]["candidates"][0]["name"] == "Noor Hasan"
    assert service.resolve_review(items[0]["id"], "merge", None, vault)["state"] == "ready"
    assert service.resolve_review(items[1]["id"], "keep", None, vault)["state"] == "ready"
    assert service.review_list(vault)["items"] == []
    assert service.status(vault)["cards"] == 2


def test_review_refuses_wrong_card(vault, service, mod):
    importer = mod("importer")
    mod("commands").handle('save "Noor Hasan" likes tea', platform="cli", vault=vault)
    with vault.write() as connection:
        importer.apply_contacts(connection, [importer.Incoming(name="Noor Hassan", details=["x"])], "test import")
    item = service.review_list(vault)["items"][0]
    assert service.resolve_review(item["id"], "merge", 999, vault) == {"state": "invalid"}
    assert service.resolve_review(item["id"], "explode", None, vault) == {"state": "invalid"}


@pytest.mark.parametrize("error,state", [("NotSetUp", "not_set_up"), ("Refused", "locked"), ("Busy", "busy")])
def test_states_map(service, mod, error, state):
    assert service.state_for(getattr(mod("vault"), error)("x")) == {"state": state}


def test_not_set_up_raises_vault_error(tmp_path, service, mod):
    fresh = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    with pytest.raises(mod("vault").NotSetUp):
        service.status(fresh)


def test_no_contact_text_in_logs(loaded, service, caplog):
    with caplog.at_level("DEBUG"):
        service.find("priya allergic", loaded)
        service.save_line(1, "private words here", loaded)
    assert "allergic" not in caplog.text and "private words" not in caplog.text
