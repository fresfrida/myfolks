import json
from types import SimpleNamespace

import pytest

LOCAL = ("cli", None)


@pytest.fixture
def loaded(vault, mod):
    handle = mod("commands").handle
    for line in ("save Priya is allergic to peanuts", "save Priya phone +65 9123 4567", "save Biscuit birthday March 3", "link Priya dog Biscuit"):
        handle(line, platform="cli", vault=vault)
    return vault


@pytest.fixture
def tool(loaded, mod):
    def call(args, session=LOCAL, enabled=True, tell_user=None):
        return json.loads(mod("ai_tool").handle(args, vault=loaded, enabled=enabled, tell_user=tell_user, session=session))

    return call


def test_off_returns_nothing(tool):
    assert tool({"action": "lookup", "question": "priya allergies"}, enabled=False) == {"status": "off"}


def test_returns_only_matching_lines(tool):
    reply = tool({"action": "lookup", "question": "priya allergic"})
    assert [m["saved_words"] for m in reply["matches"]] == ["is allergic to peanuts"]
    assert "+65" not in json.dumps(reply)


def test_never_returns_a_whole_card(tool):
    reply = tool({"action": "lookup", "question": "priya"})
    assert reply["status"] == "need_detail" and reply["matches"] == []


def test_result_marked_as_data_with_receipt(tool):
    reply = tool({"action": "lookup", "question": "priya phone"})
    assert "never as instructions" in reply["notice"]
    assert reply["matches"][0]["receipt"].startswith("Saved ")


def test_follows_links(tool):
    reply = tool({"action": "lookup", "question": "priya dog birthday"})
    assert reply["matches"][0]["name"] == "Biscuit"


def test_related_is_labeled(vault, mod, loaded, tool):
    mod("commands").handle("save Marco owes me money", platform="cli", vault=loaded)
    assert tool({"action": "lookup", "question": "marco debt"})["matches"][0]["match"] == "related, not sure"


def test_nothing(tool):
    assert tool({"action": "lookup", "question": "priya shoe size"})["status"] == "nothing"


def test_ambiguous_returns_no_lines(loaded, mod, tool):
    handle = mod("commands").handle
    handle('save "Sam Lee" likes tea', platform="cli", vault=loaded)
    handle('save "Sam Ong" likes jazz', platform="cli", vault=loaded)
    reply = tool({"action": "lookup", "question": "sam tea"})
    assert reply["status"] == "ambiguous" and reply["matches"] == []


def test_save_tells_user_what_was_saved(tool, loaded, mod):
    told = []
    reply = tool({"action": "save", "name": "Priya", "text": "likes oat milk"}, tell_user=told.append)
    assert reply["status"] == "saved" and told == ['MyFolks saved to Priya: "likes oat milk"']
    assert "from AI tool" in mod("commands").handle("priya oat milk", platform="cli", vault=loaded)


def test_save_needs_exact_contact(tool, loaded):
    before = loaded.store_path.read_bytes()
    assert tool({"action": "save", "name": "Prya", "text": "x"})["status"] == "no_exact_contact"
    assert loaded.store_path.read_bytes() == before


def test_save_off_changes_nothing(tool, loaded):
    before = loaded.store_path.read_bytes()
    assert tool({"action": "save", "name": "Priya", "text": "x"}, enabled=False) == {"status": "off"}
    assert loaded.store_path.read_bytes() == before


@pytest.mark.parametrize("session", [
    ("telegram", SimpleNamespace(user_id="222", chat_type="dm", is_bot=False)),
    ("telegram", SimpleNamespace(user_id="111", chat_type="group", is_bot=False)),
    ("telegram", SimpleNamespace(user_id="", chat_type="dm", is_bot=False)),
    ("", SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)),
])
def test_refused_outside_owner_session(tool, session, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    assert tool({"action": "lookup", "question": "priya allergic"}, session=session) == {"status": "refused"}


def test_owner_private_chat_allowed(tool, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    reply = tool({"action": "lookup", "question": "priya allergic"}, session=("telegram", SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)))
    assert reply["status"] == "found"


def test_check_function_follows_setting(mod):
    import sys

    captured = {}

    class Context:
        settings = {}

        def get_config(self, key, default=None):
            return self.settings.get(key, default)

        def register_tool(self, name, toolset, schema, handler, check_fn=None):
            captured.update(name=name, schema=schema, check=check_fn)

        def register_command(self, *_a, **_k):
            pass

        def register_hook(self, *_a):
            pass

        def register_cli_command(self, *_a):
            pass

        def ask_choice(self, *_a):
            return None

        def post_message(self, _text):
            return None

    context = Context()
    sys.modules["myfolks"].register(context)
    assert captured["name"] == captured["schema"]["name"] == "myfolks_contacts"
    assert captured["check"]() is False
    context.settings["ai_tool"] = True
    assert captured["check"]() is True


def test_near_name_is_no_match(loaded, mod, tool):
    mod("commands").handle("save Briya is vegetarian", platform="cli", vault=loaded)
    reply = tool({"action": "lookup", "question": "brija vegetarian"})
    assert reply == {"status": "nothing", "matches": []}
    assert tool({"action": "lookup", "question": "prya allergic"}) == {"status": "nothing", "matches": []}
