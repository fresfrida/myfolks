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
    assert run("priya allergic peanuts") == "Priya\nis allergic to peanuts\ntoday · terminal"


def test_unknown_person_says_nothing(run):
    assert run("nobody birthday") == "No one called nobody yet."


def test_card_view_has_no_numbers(run):
    run("save Priya likes tea")
    run("save Priya likes cake")
    assert run("priya").split("\n")[:3] == ["Priya", "likes tea", "likes cake"]


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
    assert run("priya") == "No one called priya yet."
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
        assert run(question).startswith('Biscuit\nbirthday March 3'), question


def test_link_works_both_ways(run):
    run("save Priya phone +1 202 555 0147")
    run("save Biscuit likes walks")
    run("link Priya dog Biscuit")
    assert run("biscuit owner phone").startswith('Priya\nphone +1 202 555 0147')
    assert "Dog of Priya" in run("biscuit")
    assert "Dog: Biscuit" in run("priya")


def test_link_creates_unknown_cards(run):
    assert run("link Priya dog Biscuit") == "Linked: Priya, dog, Biscuit.\nNew card for Priya.\nNew card for Biscuit."


def test_link_twice(run):
    run("link Priya dog Biscuit")
    assert run("link Priya dog Biscuit") == "Already linked."


def test_link_of_form_reverses(run):
    run("link Biscuit dog of Priya")
    assert "Dog: Biscuit" in run("priya")


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
    assert run("priya pet birthday").startswith("Biscuit\n")
    assert run("priya puppy birthday").startswith("Biscuit\n")


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
    run("save Priya phone +1 202 555 0147")
    run("save Priya email Priya@Example.com")
    run("save Priya birthday March 3")
    run("save Priya born 1990-07-21")
    run("save Priya phone number is unknown")
    with vault.read() as connection:
        rows = connection.execute("SELECT field,norm_value,birth_year,birth_month,birth_day FROM details ORDER BY id").fetchall()
    assert tuple(rows[0]) == ("phone", "+12025550147", None, None, None)
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
    assert mod("commands").handle("", platform="cli", vault=instance) == "Run hermes myfolks setup in your own terminal."


def test_handler_needs_no_import_after_register(monkeypatch):
    import sys

    package = sys.modules["myfolks"]
    captured = {}

    class Context:
        def register_command(self, name, handler, **_kwargs):
            captured[name] = handler

        def register_hook(self, *_args):
            pass

        def register_cli_command(self, *_args):
            pass

        def register_tool(self, *_args, **_kwargs):
            pass

        def get_config(self, _key, default=None):
            return default

        def ask_choice(self, *_args):
            return None

        def post_message(self, _text):
            return None

    package.register(Context())
    monkeypatch.setattr(package, "__path__", [])
    monkeypatch.delitem(sys.modules, "myfolks.commands")
    monkeypatch.delattr(package, "commands", raising=False)
    assert isinstance(captured["contacts"]("", platform="telegram"), str)


def test_exact_name_always_wins_over_close(run):
    run("save Prya likes tea")
    run("save --new Priya likes cake")
    assert run("prya").startswith("Prya\n")
    assert run("priya").startswith("Priya\n")


def test_near_name_shows_no_details_and_asks(run):
    run("save Briya is allergic to peanuts")
    reply = run("priya allergy", answer=None)
    assert reply.split("\n")[0] == "Did you mean Briya?"
    assert "allergic" not in reply and "peanuts" not in reply
    assert "/contacts Briya allergy" in reply


def test_choosing_near_name_then_shows_details(run):
    run("save Briya is allergic to peanuts")
    reply = run("priya allergy", answer=lambda choices: choices[0]["value"])
    assert [c["label"] for c in run.state["asked"]] == ["Briya", "Cancel"]
    assert 'Briya\nis allergic to peanuts' in reply


def test_cancel_shows_nothing(run):
    run("save Briya is allergic to peanuts")
    reply = run("priya allergy", answer=lambda choices: "cancel")
    assert reply == "Nothing was changed."


def test_exact_name_opens_with_no_question_when_both_saved(run):
    run("save Briya likes tea")
    run("save --new Priya likes cake")
    assert run("priya").startswith("Priya\n") and run.state["asked"] is None
    assert "likes tea" not in run("priya")


def test_marc_and_marco_never_confused(run):
    run("save Marc likes tea")
    run("save --new Marco likes jazz")
    assert run("marc").startswith("Marc\n") and run.state["asked"] is None
    assert run("marco").startswith("Marco\n") and run.state["asked"] is None


def test_only_marco_saved_does_not_open_for_marc(run):
    run("save Marco likes jazz")
    reply = run("marc", answer=None)
    assert reply.startswith("Did you mean Marco?") and "jazz" not in reply


def test_near_name_never_followed_through_links(run):
    run("save Briya likes tea")
    run("save Biscuit birthday March 3")
    run("link Briya dog Biscuit")
    reply = run("priya dog birthday", answer=None)
    assert reply.startswith("Did you mean Briya?") and "March" not in reply


def test_short_names_get_no_typo_help(run):
    run("save Bob likes cake")
    assert run("bo cake") == "No one called bo yet."


def test_several_close_names_ask(run):
    run("save Marla likes hiking")
    run("save --new Maria likes painting")
    reply = run("marca", answer=lambda choices: next(c["value"] for c in choices if "Maria" in c["label"]))
    assert [c["label"] for c in run.state["asked"]] == ["Marla", "Maria", "Cancel"] and reply.startswith("Maria\n")
    reply = run("marca", answer=None)
    assert reply.startswith("Did you mean Marla or Maria?") and "hiking" not in reply and "painting" not in reply


def test_history_with_close_name_asks_first(run):
    run("save Priya likes cake")
    reply = run("history prya", answer=None)
    assert reply.startswith("Did you mean Priya?") and "cake" not in reply and "/contacts history Priya" in reply
    assert run("history prya", answer=lambda choices: choices[0]["value"]).startswith("Priya: history")


def test_mistyped_name_on_save_asks_before_writing(run, vault):
    run("save Priya likes cake")
    before = vault.store_path.read_bytes()
    reply = run("save Prya likes tea", answer=None)
    assert reply.split("\n")[0] == "Did you mean Priya?"
    assert "/contacts save Priya likes tea" in reply
    assert "/contacts save --new Prya likes tea" in reply
    assert vault.store_path.read_bytes() == before


def test_mistyped_save_choose_existing(run):
    run("save Priya likes cake")
    reply = run("save Prya likes tea", answer=lambda choices: choices[0]["value"])
    assert reply == "Saved to Priya."
    assert [c["label"] for c in run.state["asked"]] == ["Priya", "New card for Prya"]
    assert "likes tea" in run("priya")


def test_mistyped_save_choose_new(run):
    run("save Priya likes cake")
    assert run("save Prya likes tea", answer=lambda choices: "new") == "New card for Prya. Saved."
    assert "likes tea" in run("prya") and "likes tea" not in run("priya")


def test_new_flag_skips_the_question(run):
    run("save Priya likes cake")
    assert run("save --new Prya likes tea") == "New card for Prya. Saved."


def test_question_is_asked_with_store_unlocked(run, vault, mod):
    run("save Priya likes cake")

    def answer(choices):
        with vault.read() as connection:
            connection.execute("SELECT 1")
        return choices[0]["value"]

    other = mod("vault").Vault(vault.directory, keys=vault.keys, lock_timeout=0.05)
    assert mod("commands").handle(
        "save Prya likes tea", platform="cli", vault=other,
        ask=lambda _q, choices: answer(choices),
    ) == "Saved to Priya."


def test_mistyped_name_on_link_asks(run, vault):
    run("save Priya likes cake")
    run("save Biscuit likes walks")
    before = vault.store_path.read_bytes()
    reply = run("link Prya dog Biscuit", answer=None)
    assert reply.split("\n")[0] == "Did you mean Priya?"
    assert "/contacts link Priya dog Biscuit" in reply and "/contacts link --new Prya dog Biscuit" in reply
    assert vault.store_path.read_bytes() == before
    assert run("link Prya dog Biscuit", answer=lambda choices: choices[0]["value"]) == "Linked: Priya, dog, Biscuit."


def test_mistyped_right_name_on_link_asks(run):
    run("save Priya likes cake")
    run("save Biscuit likes walks")
    reply = run("link Priya dog Biscut", answer=None)
    assert "/contacts link Priya dog Biscuit" in reply


def test_correct_with_close_name_asks(run):
    run("save Priya lives in Oslo")
    assert run("correct Prya 1 lives in Bergen", answer=None).split("\n")[0] == "Did you mean Priya?"
    assert "lives in Oslo" in run("priya")
    assert run("correct Prya 1 lives in Bergen", answer=lambda choices: choices[0]["value"]) == "Saved to Priya."


@pytest.mark.parametrize("typed,text,expected_start", [
    ("sav", "Priya likes cake", "Saved to Priya."),
    ("svae", "Priya likes cake", "Saved to Priya."),
    ("hisory", "Priya", "Priya: history"),
    ("undoo", "", "Undone:"),
    ("reviw", "", "Nothing to review."),
    ("lnik", "Priya dog Biscuit", "Linked: Priya, dog, Biscuit."),
    ("corect", "Priya 1 likes pie", "Saved to Priya."),
])
def test_mistyped_subcommands(run, typed, text, expected_start):
    run("save Priya likes tea")
    run("save Biscuit likes walks")
    assert run(f"{typed} {text}".strip()).startswith(expected_start)


def test_subcommand_typo_yields_to_real_lookup(run):
    run("save Sane likes cake")
    assert 'Sane\nlikes cake' in run("sane cake")
    run("save Linc birthday June 2")
    assert 'Linc\nbirthday June 2' in run("linc birthday")


def test_two_close_subcommands_are_not_guessed(mod):
    assert mod("commands")._closest_verb("zzz") is None
