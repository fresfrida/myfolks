import pytest


@pytest.fixture
def run(vault, mod):
    handle = mod("commands").handle
    handle("save Priya is allergic to dogs", platform="cli", vault=vault)
    handle("save Biscuit birthday March 3", platform="cli", vault=vault)
    handle("link Priya dog Biscuit", platform="cli", vault=vault)
    return lambda text, platform="cli": handle(text, platform=platform, vault=vault)


def test_no_answer_on_linked_card_falls_back_to_start(run):
    reply = run("priya dog allergy")
    assert reply.startswith("Priya\n") and "is allergic to dogs" in reply


def test_linked_card_answer_still_wins(run):
    assert run("priya dog birthday").startswith("Biscuit\n")


def test_nothing_only_when_both_are_empty(run):
    assert run("priya dog shoe size") == "Nothing saved about that.\nNot sure what to send? /myfolks help"


def test_fallback_on_desktop_and_ai_tool(vault, mod, run):
    answer = mod("desktop_service").find("priya dog allergy", vault=vault)["answer"]
    assert answer["kind"] == "direct" and answer["card"]["name"] == "Priya"
    import json
    reply = json.loads(mod("ai_tool").handle({"action": "lookup", "question": "priya dog allergy"}, enabled=True, tell_user=lambda _t: None, vault=vault, session=("cli", None)))
    assert reply["status"] == "found" and reply["matches"][0]["name"] == "Priya"
