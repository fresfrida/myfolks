from types import SimpleNamespace

import pytest


@pytest.fixture
def wake(mod):
    return mod("wake")


@pytest.mark.parametrize("text, command", [
    ("myfolks mel dog", "/contacts mel dog"),
    ("Myfolks, mel dog", "/contacts mel dog"),
    ("MYFOLKS: mel dog", "/contacts mel dog"),
    ("myfolks , mel dog", "/contacts mel dog"),
    ("myfolks remember Mel's dog's name Ollie", "/contacts remember Mel's dog's name Ollie"),
    ("Myfolks, Remember Mel likes tea", "/contacts Remember Mel likes tea"),
    ("myfolks save Mel likes tea", "/contacts save Mel likes tea"),
    ("myfolks keep Mel likes tea", "/contacts keep Mel likes tea"),
    ("myfolks note: Mel likes tea", "/contacts note: Mel likes tea"),
    ("myfolks", "/contacts"),
    ("myfolks,", "/contacts"),
    ("myfolks remember", "/contacts remember"),
    ("  myfolks mel", "/contacts mel"),
    ("myfolks\nmel dog", "/contacts mel dog"),
    ("myfolks remembered Mel", "/contacts remembered Mel"),
])
def test_rewrites_at_the_start(wake, text, command):
    assert wake.rewrite(text, "myfolks") == command


@pytest.mark.parametrize("text", [
    "hi", "", "I installed myfolks yesterday", "myfolksy mel", "my folks mel", "/myfolks mel",
    "/contacts mel", "myfolks's thing", "tell myfolks mel", "myfolks-mel",
])
def test_leaves_everything_else(wake, text):
    assert wake.rewrite(text, "myfolks") is None


def test_custom_and_empty_wake_word(wake):
    assert wake.rewrite("Folks, mel dog", "folks") == "/contacts mel dog"
    assert wake.rewrite("myfolks mel", "folks") is None
    assert wake.rewrite("myfolks mel", "") is None
    assert wake.clean_word("  /MyFolks ") == "myfolks"


class Reader:
    def __init__(self, **values):
        self.values = values
        self.calls = 0

    def __call__(self, key, default=None):
        self.calls += 1
        return self.values.get(key, default)


def test_settings_read_once_then_refresh(wake):
    now = [0.0]
    read = Reader(wake_word="Folks")
    settings = wake.Settings(read, clock=lambda: now[0])
    for _ in range(100):
        assert settings.current().word == "folks"
    assert read.calls == 2
    read.values["wake_word"] = "pals"
    now[0] += wake.REFRESH_SECONDS
    assert settings.current().word == "pals"
    assert read.calls == 4


def test_settings_keep_last_value_when_reading_fails(wake):
    now = [0.0]

    def broken(*_args):
        raise RuntimeError("config unreadable")

    settings = wake.Settings(broken, clock=lambda: now[0])
    assert settings.current().word == "myfolks"


def test_default_setting(wake):
    settings = wake.Settings(Reader())
    assert settings.current().word == "myfolks" and settings.current().ai_on is False


def test_gateway_hook(wake):
    hook = wake.gateway_hook(wake.Settings(Reader()))
    assert hook(event=SimpleNamespace(text="Myfolks, mel dog")) == {"action": "rewrite", "text": "/contacts mel dog"}
    assert hook(event=SimpleNamespace(text="hi")) is None
    assert hook(event=SimpleNamespace(text=None)) is None
    assert hook(event=None) is None


def test_ai_note_when_ai_is_off(wake):
    hook = wake.llm_hook(wake.Settings(Reader()))
    note = hook(user_message="I installed myfolks yesterday", platform="telegram")["context"]
    assert '"myfolks" or /myfolks' in note
    assert hook(user_message="MyFolks: what is mel's dog called", platform="cli")["context"].count("/myfolks") == 1
    assert hook(user_message="hi", platform="telegram") is None
    assert hook(user_message="myfolksy", platform="telegram") is None
    assert hook(user_message=[{"type": "text", "text": "ask myfolks"}, {"type": "image_url"}], platform="telegram") is not None


def test_ai_note_has_no_contact_data(wake, vault, mod):
    mod("commands").handle("save Mel dog's name Ollie", platform="cli", vault=vault)
    hook = wake.llm_hook(wake.Settings(Reader()))
    note = hook(user_message="myfolks what is mel's dog called", platform="telegram")["context"]
    assert "Ollie" not in note and "Mel" not in note


def test_no_ai_note_when_ai_is_on(wake):
    hook = wake.llm_hook(wake.Settings(Reader(ai_tool=True)))
    assert hook(user_message="I installed myfolks yesterday", platform="telegram") is None


def test_no_ai_note_when_wake_word_is_off(wake):
    hook = wake.llm_hook(wake.Settings(Reader(wake_word="")))
    assert hook(user_message="I installed myfolks yesterday", platform="telegram") is None


def test_hooks_touch_no_store_on_non_matching_message(wake, monkeypatch, mod):
    vault_module = mod("vault")
    monkeypatch.setattr(vault_module.Vault, "read", lambda *a, **k: pytest.fail("store opened"))
    monkeypatch.setattr(vault_module.Vault, "write", lambda *a, **k: pytest.fail("store opened"))
    settings = wake.Settings(Reader())
    assert wake.gateway_hook(settings)(event=SimpleNamespace(text="hi there")) is None
    assert wake.llm_hook(settings)(user_message="hi there", platform="telegram") is None


@pytest.fixture
def chat(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    commands, wake = mod("commands"), mod("wake")
    hook = wake.gateway_hook(wake.Settings(Reader()))

    def send(text, user="111", chat_type="dm", ask=None):
        result = hook(event=SimpleNamespace(text=text))
        if result is None:
            return "TO THE AI: " + text
        command = result["text"]
        assert command.startswith("/contacts")
        source = SimpleNamespace(user_id=user, chat_type=chat_type, is_bot=False)
        return commands.handle(command[len("/contacts"):].strip(), platform="telegram", source=source, vault=vault, ask=ask)

    return send


def test_wake_word_end_to_end(chat):
    chat("myfolks save Mel likes tea")
    reply = chat("myfolks remember Mel's dog's name Ollie")
    assert reply == "Saved to Mel.\nLinked Ollie as Mel's dog. Undo: /myfolks undo"
    assert chat("Myfolks, mel dog").startswith("Ollie\nDog of Mel")
    assert "dog's name Ollie" in chat("Myfolks, mel dog name")
    assert chat("I installed myfolks yesterday") == "TO THE AI: I installed myfolks yesterday"
    assert chat("hi") == "TO THE AI: hi"


def test_wake_word_offers_link_with_buttons(chat):
    chat("myfolks save Mel likes tea")
    asked = []
    reply = chat("myfolks remember Mel's dog is called Ollie", ask=lambda q, c: asked.append(q) or "link")
    assert asked == ["Also link Ollie as Mel's dog?"]
    assert reply == "Saved to Mel.\nLinked: Mel, dog, Ollie.\nNew card for Ollie."


def test_wake_word_keeps_owner_and_group_rules(chat):
    chat("myfolks save Mel likes tea")
    assert chat("myfolks mel", user="999") == "MyFolks isn't available here."
    assert chat("myfolks mel", chat_type="group") == "MyFolks isn't available here."
    assert chat("myfolks remember Mel likes jam", user="999") == "MyFolks isn't available here."


def test_wake_word_near_name_asks_first(chat):
    chat("myfolks save Marcus likes tea")
    reply = chat("myfolks markus")
    assert reply.startswith("Did you mean Marcus?")
    assert "tea" not in reply


def test_myfolks_command_is_the_same_handler():
    import yaml_free

    context = yaml_free.FakeContext()
    import sys
    sys.modules["myfolks"].register(context)
    assert context.handlers["myfolks"] is context.handlers["contacts"]


@pytest.mark.parametrize("text", ["/myfolks priya", "/contacts priya allergy", "/contacts@fresfrida_hermesbot priya", "  /MyFolks", "/myfolks"])
def test_myfolks_command_reaching_the_ai_is_blocked(wake, text):
    for ai_on in (False, True):
        hook = wake.llm_hook(wake.Settings(Reader(ai_tool=ai_on)))
        assert hook(user_message=text, platform="telegram") == {"action": "block", "message": "Use myfolks <question> while Hermes is busy."}


def test_blocked_reply_follows_the_wake_word_and_has_no_contact_data(wake, vault, mod):
    mod("commands").handle("save Priya is allergic to peanuts", platform="cli", vault=vault)
    hook = wake.llm_hook(wake.Settings(Reader(wake_word="folks")))
    reply = hook(user_message="/myfolks priya allergy", platform="telegram")["message"]
    assert reply == "Use folks <question> while Hermes is busy." and "peanuts" not in reply


@pytest.mark.parametrize("text", ["/contactsx priya", "/help", "hi /myfolks", "please /contacts priya"])
def test_other_messages_are_not_blocked(wake, text):
    result = wake.llm_hook(wake.Settings(Reader()))(user_message=text, platform="telegram")
    assert result is None or "context" in result


def test_mid_sentence_mention_keeps_the_note(wake):
    result = wake.llm_hook(wake.Settings(Reader()))(user_message="I installed myfolks yesterday", platform="telegram")
    assert "context" in result


def test_busy_reply_without_a_wake_word(wake):
    hook = wake.llm_hook(wake.Settings(Reader(wake_word="")))
    assert hook(user_message="/myfolks priya", platform="telegram") == {"action": "block", "message": "Wait until Hermes finishes, then send /myfolks again."}


@pytest.mark.parametrize("platform", ["cli", "tui", "local", "desktop", ""])
def test_busy_veto_only_in_chat_apps(wake, platform):
    result = wake.llm_hook(wake.Settings(Reader()))(user_message="/myfolks priya", platform=platform)
    assert result is None or result.get("action") != "block"
