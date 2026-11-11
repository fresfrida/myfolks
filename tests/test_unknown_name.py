import pytest


@pytest.fixture
def run(vault, mod):
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    return lambda text: mod("commands").handle(text, platform="cli", vault=vault)


@pytest.mark.parametrize("text, reply", [
    ("Tom's birthday", "No one called Tom yet."),
    ("tom’s birthday", "No one called tom yet."),
    ("James' cat", "No one called James yet."),
    ("zed", "No one called zed yet."),
    ("allergies of priyanka", "Nothing saved about that."),
    ("nobody birthday", "Nothing saved about that."),
    ("what is Tom's and Ann's address", "Nothing saved about that."),
])
def test_unknown_names(run, text, reply):
    assert run(text) == reply
