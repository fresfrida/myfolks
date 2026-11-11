"""MyFolks messages are answered at ingress and skipped, so a busy Hermes session never sees them."""
import asyncio
import inspect
import statistics
import time
from types import SimpleNamespace

import pytest


class Adapter:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if self.fail:
            raise RuntimeError("network down")
        self.sent.append((chat_id, content))


class _Platform:
    value = "telegram"


PLATFORM = _Platform()


def event(text, user="111", chat_type="dm"):
    return SimpleNamespace(text=text, source=SimpleNamespace(platform=PLATFORM, chat_id="c1", chat_type=chat_type, user_id=user, is_bot=False))


@pytest.fixture
def setup(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111", "222", "333"}, False))
    monkeypatch.setattr(mod("vault"), "Vault", lambda *a, **k: vault)
    monkeypatch.setattr(mod("commands"), "Vault", lambda *a, **k: vault)
    mod("commands").handle("save Priya is allergic to peanuts", platform="cli", vault=vault)
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES('telegram','111','2026-01-01')")
    config = {"shared_people": "telegram:222:read"}
    monkeypatch.setattr(mod("owner"), "profile_of_home", lambda: None)  # this test plugin is the default profile's
    package = __import__("sys").modules["myfolks"]
    hooks = {}

    class Context:
        def register_hook(self, name, handler):
            hooks[name] = handler

        def get_config(self, key, default=None):
            return config.get(key, default)

        def __getattr__(self, _name):
            return lambda *a, **k: None

    package.register(Context())
    adapter = Adapter()
    gateway = SimpleNamespace(adapters={PLATFORM: adapter})

    def send(text, **kw):
        result = hooks["pre_gateway_dispatch"](event=event(text, **kw), gateway=gateway, session_store=None)
        return asyncio.run(result) if inspect.isawaitable(result) else result

    return SimpleNamespace(send=send, adapter=adapter, gateway=gateway, hooks=hooks, vault=vault)


@pytest.mark.parametrize("text", ["/myfolks priya allergy", "/contacts priya allergy", "/contacts@fresfrida_hermesbot priya allergy", "myfolks priya allergy", "Myfolks, priya allergy"])
def test_owner_is_answered_and_message_is_skipped(setup, text):
    assert setup.send(text) == {"action": "skip", "reason": "answered by MyFolks"}
    assert setup.adapter.sent == [("c1", "Priya\n**is allergic to peanuts**\ntoday · terminal")]


def test_owner_save_by_wake_word_is_answered_once(setup, mod):
    assert setup.send("myfolks remember Priya likes jam")["action"] == "skip"
    assert setup.adapter.sent[0][1] == "Saved to Priya. Undo: myfolks undo"
    with setup.vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM details WHERE text='likes jam'").fetchone()[0] == 1


def test_shared_reader_is_answered(setup):
    assert setup.send("/myfolks priya allergy", user="222")["action"] == "skip"


def test_stranger_passes_through_unchanged(setup):
    assert setup.send("/myfolks priya allergy", user="999") is None
    assert setup.send("myfolks priya allergy", user="999") == {"action": "rewrite", "text": "/contacts priya allergy"}
    assert setup.adapter.sent == []


def test_group_passes_through(setup):
    assert setup.send("/myfolks priya", chat_type="group") is None
    assert setup.adapter.sent == []


def test_pairing_passes_through(setup):
    assert setup.send("/contacts pair ABCD1234", user="333") is None


def test_not_set_up_passes_through(setup, mod, monkeypatch):
    monkeypatch.setattr(mod("commands"), "Vault", lambda *a, **k: SimpleNamespace(exists=lambda: False))
    assert setup.send("/myfolks priya") is None


def test_question_falls_back_to_the_command(setup):
    assert setup.send("/myfolks pryia allergy")["action"] == "skip"
    assert "To see it, send:\n/contacts Priya allergy" in setup.adapter.sent[0][1]


def test_failed_send_still_skips_so_nothing_runs_twice(setup):
    setup.gateway.adapters[PLATFORM] = Adapter(fail=True)
    assert setup.send("myfolks remember Priya likes figs")["action"] == "skip"
    with setup.vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM details WHERE text='likes figs'").fetchone()[0] == 1


def test_no_gateway_keeps_old_behaviour(setup):
    hook = setup.hooks["pre_gateway_dispatch"]
    assert hook(event=event("myfolks priya"), gateway=None) == {"action": "rewrite", "text": "/contacts priya"}
    assert hook(event=event("/myfolks priya"), gateway=None) is None


@pytest.mark.parametrize("text", ["hi", "I installed myfolks yesterday", "/help", "/new", "/contactsx priya", "/stop"])
def test_other_messages_are_untouched_and_instant(setup, text):
    hook = setup.hooks["pre_gateway_dispatch"]
    assert hook(event=event(text), gateway=setup.gateway) is None
    samples = []
    for _ in range(5000):
        started = time.perf_counter()
        hook(event=event(text), gateway=setup.gateway)
        samples.append(time.perf_counter() - started)
    assert statistics.median(samples) < 0.001 and max(samples) < 0.01


def test_unknown_name_says_no_one_by_that_name(setup):
    assert setup.send("/myfolks zed")["action"] == "skip"
    assert setup.adapter.sent == [("c1", "No one called zed yet.")]


def test_known_name_shows_the_card_through_the_hook(setup):
    setup.send("/myfolks priya")
    assert setup.adapter.sent[0][1].startswith("Priya\n")


def test_shared_person_not_on_the_bot_allow_list_passes_through(setup, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    assert setup.send("/myfolks priya allergy", user="222") is None
    assert setup.send("myfolks priya allergy", user="222") == {"action": "rewrite", "text": "/contacts priya allergy"}
    assert setup.adapter.sent == []
    assert setup.send("/myfolks priya allergy", user="111")["action"] == "skip"


def test_open_bot_lets_a_shared_person_through_ingress(setup, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: (set(), True))
    assert setup.send("/myfolks priya allergy", user="222")["action"] == "skip"


@pytest.mark.parametrize("routed", ["work", "states"])
def test_message_for_another_profile_passes_through(setup, routed):
    message = event("/myfolks priya allergy")
    message.source.profile = routed
    result = setup.hooks["pre_gateway_dispatch"](event=message, gateway=setup.gateway, session_store=None)
    result = asyncio.run(result) if inspect.isawaitable(result) else result
    assert result is None and setup.adapter.sent == []


@pytest.mark.parametrize("routed", [None, "", "default"])
def test_message_for_this_default_profile_is_answered(setup, routed):
    message = event("/myfolks priya allergy")
    message.source.profile = routed
    result = asyncio.run(setup.hooks["pre_gateway_dispatch"](event=message, gateway=setup.gateway, session_store=None))
    assert result["action"] == "skip"


def test_profile_names(mod, monkeypatch, tmp_path):
    import sys
    import types

    owner = mod("owner")
    fake = types.ModuleType("hermes_constants")
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)
    fake.get_hermes_home = lambda: tmp_path / ".hermes" / "profiles" / "work"
    assert owner.profile_of_home() == "work"
    fake.get_hermes_home = lambda: tmp_path / ".hermes"
    assert owner.profile_of_home() is None
    assert owner.routed_profile(SimpleNamespace(profile="default")) is None and owner.routed_profile(SimpleNamespace(profile="work")) == "work"
