import json
from pathlib import Path

import pytest

SET = json.loads((Path(__file__).parent / "search_set.json").read_text())
RELATED = "Related, not sure:"
NOTHING = "Nothing saved about that."


@pytest.fixture
def ask_run(vault, mod):
    commands = mod("commands")

    def go(text, choose=None):
        def ask(_question, choices):
            for choice in choices:
                if choose and choose in choice["label"]:
                    return choice["value"]
            return None

        return commands.handle(text, platform="cli", ask=ask, vault=vault)

    return go


@pytest.fixture
def loaded(ask_run):
    for line in SET["setup"]:
        ask_run(line)
    return ask_run


def outcome(item, reply):
    expect = item["expect"]
    find = item.get("find", "")
    if expect == "direct":
        return not reply.startswith(RELATED) and find in reply and reply != NOTHING
    if expect == "related":
        return reply.startswith(RELATED) and find in reply
    if expect == "nothing":
        return reply == NOTHING
    if expect == "not_direct":
        return reply.startswith(RELATED) or reply == NOTHING
    if expect == "card":
        return find in reply.split("\n")[0]
    raise AssertionError(expect)


def test_question_set_prints_score(loaded):
    assert len(SET["questions"]) >= 60
    misses = []
    for item in SET["questions"]:
        reply = loaded(item["q"], choose=item.get("choose"))
        if not outcome(item, reply):
            misses.append((item, reply))
    total = len(SET["questions"])
    print(f"\nSEARCH SCORE: {total - len(misses)}/{total} correct, {len(misses)} misses")
    for item, reply in misses:
        print(f"MISS [{item['expect']}] {item['q']!r}" + (f" choose={item['choose']}" if "choose" in item else "") + f" -> {reply.splitlines()[0]!r}" + (f" | {reply.splitlines()[1]!r}" if len(reply.splitlines()) > 1 else ""))
    wrong_direct = [item for item, reply in misses if item["expect"] in ("nothing", "not_direct") and not reply.startswith(RELATED) and reply != NOTHING]
    assert not wrong_direct, "a question with no answer returned a direct answer"


@pytest.mark.parametrize("question", ["priya allergy", "priya alergic"])
def test_known_case_allergy_finds_line(loaded, question):
    assert "allergic to peanuts" in loaded(question)


def test_known_case_favorite_food_is_not_direct(loaded):
    reply = loaded("priya favorite food")
    assert reply.startswith(RELATED) or reply == NOTHING


def test_known_case_shoe_size_is_nothing(loaded):
    assert loaded("priya shoe size") == NOTHING


def test_answer_prints_stored_words_exactly(ask_run):
    ask_run("save Priya Is ALLERGIC, to Peanuts!!")
    assert 'Priya: "Is ALLERGIC, to Peanuts!!"' in ask_run("priya allergic")


def test_closed_lines_are_not_searched(ask_run):
    ask_run("save Priya lives in Oslo")
    ask_run("correct Priya 1 moved to Bergen")
    assert ask_run("priya oslo") == NOTHING


def test_search_stays_on_one_person(ask_run):
    ask_run("save Priya likes tea")
    ask_run("save Marco likes jazz")
    assert ask_run("priya jazz") == NOTHING


def test_concept_list_never_direct(ask_run):
    ask_run("save Marco owes me money")
    assert ask_run("marco debt").startswith(RELATED)


def test_no_network_or_model_imports():
    root = Path(__file__).parent.parent
    banned = ("socket", "http.client", "urllib", "requests", "httpx", "aiohttp", "openai", "anthropic", "agent.plugin_llm")
    for path in root.glob("*.py"):
        source = path.read_text()
        for name in banned:
            assert f"import {name}" not in source and f"from {name}" not in source, (path.name, name)
        assert "ctx.llm" not in source, path.name
