import pytest


@pytest.fixture
def run(vault, mod):
    handle = mod("commands").handle
    handle('save "Studio 54" opens at nine', platform="cli", vault=vault)
    handle('save "Studio 54" has a red door', platform="cli", vault=vault)
    handle("save Loft rents by the hour", platform="cli", vault=vault)
    return lambda text: handle(text, platform="cli", vault=vault)


def test_name_with_a_number(run):
    assert run("correct Studio 54 2 has a blue door") == "Changed. Undo: /myfolks undo"
    assert "has a blue door" in run('"studio 54" door')
    assert "rents by the hour" in run("loft hour")


def test_plain_name_still_works(run):
    assert run("correct Loft 1 rents by the day") == "Changed. Undo: /myfolks undo"
    assert "rents by the day" in run("loft day")


def test_name_with_a_number_and_no_line_lists_lines(run):
    reply = run("correct Studio 54")
    assert reply.startswith("Studio 54\n1. opens at nine")
