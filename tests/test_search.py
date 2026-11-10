import json
from pathlib import Path

import pytest

SET = json.loads((Path(__file__).parent / "search_set.json").read_text())
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


def is_unsure(reply):
    return reply.split("\n")[0].endswith(" · not sure")


def body_of(reply):
    return reply


def outcome(item, reply):
    reply = body_of(reply)
    expect = item["expect"]
    find = item.get("find", "")
    if expect == "ask":
        return reply.startswith(find) and '"' not in reply.split("To see it")[0]
    if expect == "direct":
        return not is_unsure(reply) and find in reply and reply != NOTHING
    if expect == "related":
        return is_unsure(reply) and find in reply
    if expect == "nothing":
        return reply == NOTHING
    if expect == "not_direct":
        return is_unsure(reply) or reply == NOTHING
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
    wrong_direct = [(item, reply) for item, reply in misses if item["expect"] in ("nothing", "not_direct") and not is_unsure(reply) and body_of(reply) != NOTHING]
    for item, reply in wrong_direct:
        print(f"WRONG ANSWER LABELED DIRECT: {item['q']!r} -> {reply.splitlines()[0]!r}")
    assert not wrong_direct, "a question with no answer returned a direct answer"


@pytest.mark.parametrize("question", ["priya allergy", "priya alergic"])
def test_known_case_allergy_finds_line(loaded, question):
    assert "allergic to peanuts" in loaded(question)


def test_known_case_favorite_food_is_not_direct(loaded):
    reply = loaded("priya favorite food")
    assert is_unsure(reply) or reply == NOTHING


def test_known_case_shoe_size_is_nothing(loaded):
    assert loaded("priya shoe size") == NOTHING


def test_answer_prints_stored_words_exactly(ask_run):
    ask_run("save Priya Is ALLERGIC, to Peanuts!!")
    assert 'Priya\nIs ALLERGIC, to Peanuts!!' in ask_run("priya allergic")


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
    assert is_unsure(ask_run("marco debt"))


def test_no_network_or_model_imports():
    root = Path(__file__).parent.parent
    banned = ("socket", "http.client", "urllib", "requests", "httpx", "aiohttp", "openai", "anthropic", "agent.plugin_llm")
    for path in root.glob("*.py"):
        source = path.read_text()
        for name in banned:
            assert f"import {name}" not in source and f"from {name}" not in source, (path.name, name)
        assert "ctx.llm" not in source, path.name


@pytest.mark.parametrize("question,find", [("priya penuts", "allergic to peanuts"), ("marco passprot", "renewal"), ("marco sugr", "no sugar")])
def test_named_typos_found(loaded, question, find):
    reply = loaded(question)
    assert find in reply and not is_unsure(reply)


def test_no_typo_rule_under_five_letters(mod):
    alike = mod("search").spelled_alike
    assert not alike("hat", "cat") and not alike("rope", "ripe") and alike("sugr", "sugar")


def test_one_edit_rules(mod):
    edit = mod("text").one_edit_apart
    assert edit("penuts", "peanuts") and edit("peanuts", "penuts")
    assert edit("passprot", "passport")
    assert edit("colour", "colout")
    assert not edit("same", "same") and not edit("mother", "brother") and not edit("abcd", "dcba")


def test_exact_match_ranks_before_typo(ask_run):
    ask_run("save Asha lives in Chennai")
    ask_run("save Asha loves tulips")
    assert ask_run("asha loves").split("\n")[1] == "loves tulips"


def test_typo_never_makes_partial_match_direct(ask_run):
    ask_run("save Marco passport renewal due")
    assert ask_run("marco passprot visa") in (NOTHING,) or is_unsure(ask_run("marco passprot visa"))


@pytest.mark.parametrize("question,find", [("marco bears", "size 42"), ("sam lee chest", "chess"), ("priya lines", "Queenstown")])
def test_changed_letter_is_only_related(loaded, question, find):
    reply = loaded(question)
    assert is_unsure(reply) and find in reply


def test_changed_letter_helper(mod):
    changed = mod("text").changed_one_letter
    assert changed("bears", "wears", 5) and changed("chest", "chess", 5)
    assert not changed("penuts", "peanuts", 5) and not changed("wears", "wears", 5) and not changed("cat", "car", 5)


def test_priya_likes_finds_all_synonyms_as_direct(ask_run):
    ask_run("save Priya likes tea")
    ask_run("save Priya favourite colour is green")
    ask_run("save Priya prefers window seats")
    ask_run("save Priya loves hiking")
    ask_run("save Priya enjoys chess")
    reply = ask_run("priya likes")
    assert not is_unsure(reply)
    for words in ("likes tea", "favourite colour is green", "prefers window seats", "loves hiking", "enjoys chess"):
        assert words in reply


def test_every_important_word_must_still_match(ask_run):
    ask_run("save Priya likes tea")
    reply = ask_run("priya likes hiking")
    assert not reply.startswith("Priya\nlikes tea") or is_unsure(reply)


def test_what_can_she_eat_stays_not_sure(ask_run):
    ask_run("save Priya is allergic to peanuts")
    reply = ask_run("what can priya eat")
    assert is_unsure(reply) and "allergic to peanuts" in reply


@pytest.mark.parametrize("question", ["priya allergy", "priya allergies", "priya allergic"])
def test_allergy_words_are_synonyms(ask_run, question):
    ask_run("save Priya is allergic to peanuts")
    assert not is_unsure(ask_run(question)) and "peanuts" in ask_run(question)


def test_food_finding_allergic_is_only_a_topic_link(ask_run):
    ask_run("save Priya is allergic to shellfish")
    assert is_unsure(ask_run("priya food"))


def test_a_topic_never_counts_as_direct(ask_run):
    ask_run("save Marco owes me money")
    assert is_unsure(ask_run("marco debt"))


def test_synonym_and_topic_lists_are_separate(mod):
    data = mod("text").load_data("concepts.json")
    assert set(data) >= {"synonyms", "topics"} and "groups" not in data
