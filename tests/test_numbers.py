import pytest

ODD = ["²", "٣", "３", "①", "Ⅻ", "1²", "¹2"]


@pytest.fixture
def run(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    handle("save Priya likes jam", platform="cli", vault=vault)
    return lambda text: handle(text, platform="cli", vault=vault)


@pytest.mark.parametrize("odd", ODD)
def test_hide_and_unhide(run, odd):
    usage = "To hide: /contacts hide <name> <line number>. To show again: /contacts unhide <name> <line number>."
    assert run(f"hide priya {odd}") == usage
    assert run(f"unhide priya {odd}") == usage


@pytest.mark.parametrize("odd", ODD)
def test_correct(run, odd):
    reply = run(f"correct priya {odd} likes coffee")
    assert reply.startswith("To correct") and "Something went wrong" not in reply
    assert "likes tea" in run("priya tea")


@pytest.mark.parametrize("odd", ODD)
def test_review(run, odd):
    assert "Something went wrong" not in run(f"review merge {odd}")
    assert "Something went wrong" not in run(f"review merge 1 #{odd}")
    assert "Something went wrong" not in run(f"review keep {odd}")


@pytest.mark.parametrize("odd", ODD)
def test_card_number(run, odd):
    assert run(f"#{odd}") == "Nothing saved about that."


def test_ascii_numbers_still_work(run):
    assert run("hide priya 1").startswith("Hidden from chat.")
    assert run("correct priya 2 likes marmalade") == "Changed. Undo: /myfolks undo"
    assert run("#1").startswith("Priya")


def test_parser(mod):
    text = mod("text")
    assert text.ascii_number("42") == 42 and text.ascii_number("²") is None and text.ascii_number("٣") is None
    assert text.looks_numeric("²") and not text.looks_numeric("Studio")
