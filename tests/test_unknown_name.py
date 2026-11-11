import pytest


@pytest.fixture
def run(vault, mod):
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    return lambda text: mod("commands").handle(text, platform="cli", vault=vault)


@pytest.mark.parametrize("text, reply", [
    ("Tom's birthday", "No one called Tom yet.\nNot sure what to send? /myfolks help"),
    ("tom’s birthday", "No one called tom yet.\nNot sure what to send? /myfolks help"),
    ("James' cat", "No one called James yet.\nNot sure what to send? /myfolks help"),
    ("zed", "No one called zed yet.\nNot sure what to send? /myfolks help"),
    ("allergies of priyanka", "Nothing saved about that.\nNot sure what to send? /myfolks help"),
    ("nobody birthday", "Nothing saved about that.\nNot sure what to send? /myfolks help"),
    ("what is Tom's and Ann's address", "Nothing saved about that.\nNot sure what to send? /myfolks help"),
])
def test_unknown_names(run, text, reply):
    assert run(text) == reply
