from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

LOCAL = datetime.now().astimezone().tzinfo


def at(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=LOCAL)


NOW = at(2026, 11, 10)


@pytest.fixture
def m(mod):
    return mod("messages")


@pytest.mark.parametrize("saved,expected", [
    (at(2026, 11, 10, 0, 1), "today"),
    (at(2026, 11, 10, 23, 59), "today"),
    (at(2026, 11, 9, 23, 59), "November this year"),
    (at(2026, 6, 15), "June this year"),
    (at(2026, 1, 1, 0, 0), "January this year"),
    (at(2025, 12, 31, 23, 59), "last year"),
    (at(2025, 1, 1, 0, 0), "last year"),
    (at(2024, 12, 31, 23, 59), "more than a year ago"),
    (at(2019, 3, 3), "more than a year ago"),
])
def test_date_labels(m, saved, expected):
    assert m.date_label(saved.isoformat(), now=NOW) == expected


def test_new_year_boundary(m):
    now = at(2027, 1, 1, 0, 5)
    assert m.date_label(at(2026, 12, 31, 23, 59).isoformat(), now=now) == "last year"
    assert m.date_label(at(2027, 1, 1, 0, 1).isoformat(), now=now) == "today"
    assert m.date_label(at(2025, 12, 31).isoformat(), now=now) == "more than a year ago"


def test_uses_local_time_not_utc(m):
    utc_saved = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
    assert m.date_label(utc_saved.isoformat(), now=utc_saved.astimezone()) == "today"


def test_clock_skew_counts_as_today(m):
    assert m.date_label((NOW + timedelta(days=1)).isoformat(), now=NOW) == "today"


def text(m, name, lines, unsure=False):
    return m.answer(name, lines, unsure=unsure, render=str, now=NOW)


def test_format_same_receipt_two_lines(m):
    saved = at(2026, 11, 10).isoformat()
    assert text(m, "Priya", [("likes tea", saved, "Telegram"), ("likes ZQXSAVE7 tea", saved, "Telegram")]) == (
        "Priya\nlikes tea\nlikes ZQXSAVE7 tea\ntoday · Telegram"
    )


def test_format_one_line_this_year(m):
    assert text(m, "Priya", [("is allergic to peanuts", at(2026, 6, 2).isoformat(), "Telegram")]) == (
        "Priya\nis allergic to peanuts\nJune this year · Telegram"
    )


def test_format_different_dates_end_each_line_with_date_only(m):
    lines = [("is allergic to peanuts", at(2025, 2, 2).isoformat(), "terminal"), ("likes tea", at(2026, 6, 2).isoformat(), "Telegram")]
    assert text(m, "Priya", lines) == "Priya\nis allergic to peanuts · last year\nlikes tea · June this year"


def test_format_different_dates_same_source_also_has_no_source(m):
    lines = [("x", at(2025, 2, 2).isoformat(), "terminal"), ("y", at(2026, 6, 2).isoformat(), "terminal")]
    assert text(m, "A", lines) == "A\nx · last year\ny · June this year"


def test_format_not_sure(m):
    assert text(m, "Marco", [("wears size 42 shoes", at(2023, 1, 1).isoformat(), "terminal")], unsure=True) == (
        "Marco · not sure\nwears size 42 shoes\nmore than a year ago · terminal"
    )


def test_same_date_different_sources_ends_with_date_only(m):
    saved = at(2026, 11, 10).isoformat()
    assert text(m, "A", [("x", saved, "terminal"), ("y", saved, "Telegram")]) == "A\nx\ny\ntoday"


def test_same_date_and_source_keeps_full_receipt(m):
    saved = at(2026, 11, 10).isoformat()
    assert text(m, "A", [("x", saved, "terminal"), ("y", saved, "terminal")]) == "A\nx\ny\ntoday · terminal"


def test_telegram_bolds_only_saved_words(m):
    saved = at(2026, 6, 2).isoformat()
    assert m.answer("Priya", [("likes tea", saved, "Telegram")], unsure=False, render=m.telegram_words, now=NOW) == (
        "Priya\n**likes tea**\nJune this year · Telegram"
    )


def test_telegram_mixed_keeps_receipt_plain(m):
    lines = [("a b", at(2026, 6, 2).isoformat(), "Telegram"), ("c d", at(2025, 6, 2).isoformat(), "terminal")]
    assert m.answer("N", lines, unsure=False, render=m.telegram_words, now=NOW) == (
        "N\n**a b** · June this year\n**c d** · last year"
    )


@pytest.mark.parametrize("words", ["snake_case name", "2*3 is 6", "*starred*", "~~gone~~", "||hidden||", "[a](https://b.co)", "# heading", "> quote", "cost $5", "back\\slash"])
def test_formatting_characters_go_in_a_code_span_unchanged(m, words):
    assert m.telegram_words(words) == f"`{words}`"


@pytest.mark.parametrize("words", ["has `ticks` inside", "two\nlines"])
def test_backticks_or_new_lines_use_a_code_block(m, words):
    assert m.telegram_words(words) == f"```\n{words}\n```"


def test_code_block_receipt_goes_on_its_own_line(m):
    lines = [("a `b`", at(2026, 6, 2).isoformat(), "Telegram"), ("c", at(2025, 6, 2).isoformat(), "terminal")]
    assert m.answer("N", lines, unsure=False, render=m.telegram_words, now=NOW) == (
        "N\n```\na `b`\n```\nJune this year\n**c** · last year"
    )


@pytest.mark.parametrize("words", ["*a* _b_ `c`", "~~d~~ ||e||", "plain"])
def test_terminal_shows_saved_words_exactly(vault, mod, words):
    handle = mod("commands").handle
    handle(f"save Priya mark7 {words}", platform="cli", vault=vault)
    assert f"mark7 {words}" in handle("priya mark7", platform="cli", vault=vault).split("\n")[1]


def seed_dates(vault, rows):
    with vault.write() as connection:
        for row_id, saved_at, source in rows:
            connection.execute("UPDATE details SET saved_at=?, source=? WHERE id=?", (saved_at, source, row_id))


def dm():
    return SimpleNamespace(user_id="111", chat_type="dm", is_bot=False)


@pytest.fixture
def phone(vault, mod, monkeypatch):
    monkeypatch.setattr(mod("owner"), "allowed_users", lambda platform: ({"111"}, False))
    return lambda text: mod("commands").handle(text, platform="telegram", source=dm(), vault=vault)


def test_end_to_end_telegram_bold(phone):
    assert phone("save Priya likes tea") == "New card for Priya. Saved."
    assert phone("priya tea") == "Priya\n**likes tea**\ntoday · Telegram"


def test_end_to_end_terminal_has_no_asterisks(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    assert handle("priya tea", platform="cli", vault=vault) == "Priya\nlikes tea\ntoday · terminal"


def test_end_to_end_unsure_on_telegram(phone):
    phone("save Marco owes me money")
    assert phone("marco debt") == "Marco · not sure\n**owes me money**\ntoday · Telegram"


def test_end_to_end_mixed_dates(vault, mod, phone):
    phone("save Priya likes tea")
    phone("save Priya likes cake")
    seed_dates(vault, [(1, at(2020, 1, 1).isoformat(), "terminal")])
    assert phone("priya likes") == "Priya\n**likes tea** · more than a year ago\n**likes cake** · today"


def test_history_keeps_exact_dates(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    assert str(datetime.now().year) in handle("history priya", platform="cli", vault=vault)


def test_desktop_receipt_keeps_exact_date(vault, mod):
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    assert str(datetime.now().year) in mod("desktop_service").card_detail(1, vault)["lines"][0]["receipt"]


def test_more_line_when_over_the_limit(vault, mod):
    handle = mod("commands").handle
    for number in range(11):
        handle(f"save Priya likes thing{number}", platform="cli", vault=vault)
    lines = handle("priya likes", platform="cli", vault=vault).split("\n")
    assert len([line for line in lines if line.startswith("likes thing")]) == 8
    assert lines[-1] == "+3 more · /contacts Priya"


def test_no_more_line_at_exactly_the_limit(vault, mod):
    handle = mod("commands").handle
    for number in range(8):
        handle(f"save Priya likes thing{number}", platform="cli", vault=vault)
    reply = handle("priya likes", platform="cli", vault=vault)
    assert "more ·" not in reply and reply.count("likes thing") == 8


def test_more_line_is_plain_on_telegram(phone):
    for number in range(9):
        phone(f"save Priya likes thing{number}")
    assert phone("priya likes").split("\n")[-1] == "+1 more · /contacts Priya"


def test_card_view_exact_format(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    handle("save Priya phone +65 9123 4567", platform="cli", vault=vault)
    handle("save Biscuit likes walks", platform="cli", vault=vault)
    handle("link Priya dog Biscuit", platform="cli", vault=vault)
    assert handle("priya", platform="cli", vault=vault) == "Priya\nlikes tea\nphone +65 9123 4567\nDog: Biscuit\n2 notes · last saved today"
    assert handle("biscuit", platform="cli", vault=vault) == "Biscuit\nlikes walks\nDog of Priya\n1 note · last saved today"


def test_card_uses_latest_date_label(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    handle("save Priya likes cake", platform="cli", vault=vault)
    seed_dates(vault, [(1, at(2020, 1, 1).isoformat(), "terminal"), (2, at(2021, 1, 1).isoformat(), "terminal")])
    assert handle("priya", platform="cli", vault=vault).split("\n")[-1] == "2 notes · last saved more than a year ago"


def test_card_on_telegram_has_private_line_after_notes(phone, vault, mod):
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    mod("commands").handle("save --private Priya sees a therapist", platform="cli", vault=vault)
    assert phone("priya") == "Priya\nlikes tea\n1 note · last saved today\n1 private note · on your computer"


def test_card_with_only_private_notes_on_telegram(phone, vault, mod):
    mod("commands").handle("save --private Priya secret line", platform="cli", vault=vault)
    assert phone("priya") == "Priya\n1 private note · on your computer"


def test_card_keeps_formatting_characters_exact_on_telegram(phone, vault, mod):
    mod("commands").handle("save Priya uses 2*3 _here_", platform="cli", vault=vault)
    assert "`uses 2*3 _here_`" in phone("priya")


def test_correct_with_only_a_name_lists_numbered_lines(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    handle("save Priya likes cake", platform="cli", vault=vault)
    lines = handle("correct priya", platform="cli", vault=vault).split("\n")
    assert lines[:3] == ["Priya", "1. likes tea", "2. likes cake"] and lines[3].startswith("To correct:")
    assert str(datetime.now().year) not in "\n".join(lines)


def test_correct_list_on_messaging_hides_private_lines(phone, vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    handle("save --private Priya secret line", platform="cli", vault=vault)
    handle("save Priya likes cake", platform="cli", vault=vault)
    reply = phone("correct priya")
    assert "secret" not in reply and "2. likes cake" in reply


def test_correct_list_near_name_asks_with_no_details(vault, mod):
    handle = mod("commands").handle
    handle("save Priya likes tea", platform="cli", vault=vault)
    reply = handle("correct prya", platform="cli", vault=vault)
    assert reply.startswith("Did you mean Priya?") and "likes tea" not in reply


def test_correct_with_unknown_name_shows_usage(vault, mod):
    assert mod("commands").handle("correct nobody", platform="cli", vault=vault).startswith("To correct:")


def test_history_on_telegram_shows_formatting_characters_exactly(phone, vault, mod):
    mod("commands").handle("save Priya uses 2*3 _here_", platform="cli", vault=vault)
    assert "`uses 2*3 _here_`\nSaved " in phone("history priya")


def test_history_on_telegram_keeps_quotes_on_plain_words(phone, vault, mod):
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    assert '"likes tea"\nSaved ' in phone("history priya")


def test_history_on_telegram_uses_a_block_for_backticks(phone, vault, mod):
    mod("commands").handle("save Priya has `ticks` here", platform="cli", vault=vault)
    assert "```\nhas `ticks` here\n```\nSaved " in phone("history priya")


def test_history_in_terminal_is_unchanged(vault, mod):
    handle = mod("commands").handle
    handle("save Priya uses 2*3 _here_", platform="cli", vault=vault)
    assert '"uses 2*3 _here_"\nSaved ' in handle("history priya", platform="cli", vault=vault)
