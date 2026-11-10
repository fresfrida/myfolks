import pytest


@pytest.fixture
def run(vault, mod):
    commands = mod("commands")
    state = {"answer": None}

    def go(text, platform="cli", answer=None):
        state["asked"] = None

        def ask(question, choices):
            state["asked"] = choices
            return answer(choices) if callable(answer) else answer

        return commands.handle(text, platform=platform, ask=ask, vault=vault)

    go.state = state
    return go


def test_empty_shows_help_and_count(run):
    assert run("").startswith("MyFolks: 0 cards.")
    run("save Priya likes tea")
    assert run("").startswith("MyFolks: 1 card.")


def test_save_new_then_existing_card(run):
    run("save Warmup likes tea")
    assert run("save Priya is allergic to peanuts") == "New card for Priya. Saved."
    assert run("save priya likes tea") == "Saved to Priya."


def test_save_keeps_words_exactly(run):
    run("save Priya   Likes  TEA, not coffee!")
    assert 'Likes  TEA, not coffee!' in run("priya")


def test_save_needs_text(run):
    assert run("save Priya") == "To save: /contacts save <name> <text>"


def test_save_multiword_name_with_quotes(run):
    run("save Warmup likes tea")
    assert run('save "Priya Sharma" likes tea') == "New card for Priya Sharma. Saved."
    assert run("save priya sharma drinks water") == "Saved to Priya Sharma."
    assert "likes tea" in run("priya sharma")


def test_first_name_is_alias_for_full_name(run):
    run('save "Priya Sharma" likes tea')
    assert "likes tea" in run("priya")


def test_lookup_answer_format(run):
    run("save Priya is allergic to peanuts")
    reply = run("priya allergic peanuts")
    first, second = reply.split("\n")
    assert first == 'Priya: "is allergic to peanuts"'
    assert second.startswith("Saved ") and second.endswith(" from terminal")


def test_unknown_person_says_nothing(run):
    assert run("nobody birthday") == "Nothing saved about that."


def test_card_view_numbered(run):
    run("save Priya likes tea")
    run("save Priya likes cake")
    reply = run("priya").split("\n")
    assert reply[0] == "Priya"
    assert reply[1].startswith("1. likes tea")
    assert reply[2].startswith("2. likes cake")


def test_terminal_warning_shown_once(run):
    warning = "Heads up: Hermes keeps a plain-text history of what you type in this terminal, including this command."
    assert run("save Priya likes tea") == f"New card for Priya. Saved.\n{warning}"
    assert warning not in run("save Priya likes cake")


def test_terminal_warning_not_shown_on_desktop(run):
    assert "Heads up" not in run("save Priya likes tea", platform="desktop")


def test_correct_closes_old_and_history_keeps_it(run):
    run("save Priya lives in Oslo")
    assert run("correct Priya 1 lives in Bergen") == "Saved to Priya."
    view = run("priya")
    assert "lives in Bergen" in view and "lives in Oslo" not in view
    history = run("history priya")
    assert "lives in Oslo" in history and "replaced" in history and "lives in Bergen" in history


def test_correct_bad_line_number(run):
    run("save Priya likes tea")
    assert run("correct Priya 9 likes cake") == "That line number isn't on the card."


def test_undo_save(run):
    run("save Priya likes tea")
    assert run("undo").startswith("Undone:")
    assert run("priya") == "Nothing saved about that."
    assert run("undo") == "Nothing to undo."


def test_undo_correct_restores_old_value(run):
    run("save Priya lives in Oslo")
    run("correct Priya 1 lives in Bergen")
    run("undo")
    view = run("priya")
    assert "lives in Oslo" in view and "lives in Bergen" not in view


def test_link_and_follow(run):
    run("save Priya is allergic to peanuts")
    run("save Biscuit birthday March 3")
    assert run("link Priya dog Biscuit") == "Linked: Priya, dog, Biscuit."
    for question in ("priya dog birthday", "priya's dog birthday", "what is priya's dog's birthday"):
        assert run(question).startswith('Biscuit: "birthday March 3"'), question


def test_link_works_both_ways(run):
    run("save Priya phone +65 9123 4567")
    run("save Biscuit likes walks")
    run("link Priya dog Biscuit")
    assert run("biscuit owner phone").startswith('Priya: "phone +65 9123 4567"')
    assert "dog of: Priya" in run("biscuit")
    assert "dog: Biscuit" in run("priya")


def test_link_creates_unknown_cards(run):
    assert run("link Priya dog Biscuit") == "Linked: Priya, dog, Biscuit.\nNew card for Priya.\nNew card for Biscuit."


def test_link_twice(run):
    run("link Priya dog Biscuit")
    assert run("link Priya dog Biscuit") == "Already linked."


def test_link_of_form_reverses(run):
    run("link Biscuit dog of Priya")
    assert "dog: Biscuit" in run("priya")


def test_relationship_word_as_alias(run):
    run("save Asha likes tulips")
    assert run("link me mom Asha") == "Asha also answers to mom."
    assert "likes tulips" in run("mom")
    assert "likes tulips" in run("my mom tulips")


def test_alias_form(run):
    run("save Robert likes jazz")
    run("link Robert aka Bob")
    assert "likes jazz" in run("bob")


def test_relation_synonym_and_broader_word(run):
    run("link Priya dog Biscuit")
    run("save Biscuit birthday March 3")
    assert run("priya pet birthday").startswith("Biscuit:")
    assert run("priya puppy birthday").startswith("Biscuit:")


def test_same_name_asks_and_never_guesses(run):
    run('save "Sam Lee" likes tea')
    run('save "Sam Ong" likes coffee')
    reply = run("sam", answer=lambda choices: choices[1]["value"])
    assert run.state["asked"] and len(run.state["asked"]) == 2
    assert "likes coffee" in reply


def test_same_name_with_no_answer_lists_options(run):
    run('save "Sam Lee" likes tea')
    run('save "Sam Ong" likes coffee')
    reply = run("sam tea", answer=None)
    assert reply.startswith("More than one match.") and "#1" in reply and "#2" in reply
    assert "likes tea" in run("#1")


def test_save_to_same_name_asks(run):
    run('save "Sam Lee" likes tea')
    run('save "Sam Ong" likes coffee')
    assert run("save sam plays chess", answer=None).startswith("More than one match.")
    assert "plays chess" not in run("#1") and "plays chess" not in run("#2")
    run("save sam plays chess", answer=lambda choices: choices[0]["value"])
    assert "plays chess" in run("#1")


def test_structured_values_recognized(run, vault):
    run("save Priya phone +65 9123 4567")
    run("save Priya email Priya@Example.com")
    run("save Priya birthday March 3")
    run("save Priya born 1990-07-21")
    run("save Priya phone number is unknown")
    with vault.read() as connection:
        rows = connection.execute("SELECT field,norm_value,birth_year,birth_month,birth_day FROM details ORDER BY id").fetchall()
    assert tuple(rows[0]) == ("phone", "+6591234567", None, None, None)
    assert tuple(rows[1]) == ("email", "priya@example.com", None, None, None)
    assert tuple(rows[2]) == ("birthday", None, None, 3, 3)
    assert tuple(rows[3]) == ("birthday", None, 1990, 7, 21)
    assert rows[4][0] is None


def test_refuses_messaging_without_a_source(run):
    assert run("", platform="telegram") == "MyFolks isn't available here."


def test_refuses_when_platform_missing(run):
    assert run("", platform=None) == "MyFolks isn't available here."


def test_not_set_up_message(tmp_path, mod):
    instance = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    assert "hermes myfolks setup" in mod("commands").handle("", platform="cli", vault=instance)
