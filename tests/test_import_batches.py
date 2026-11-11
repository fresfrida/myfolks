import argparse
import io
import threading
import time

import pytest

GENEROUS_LOOKUP_LIMIT = 5.0  # seconds


class Terminal(io.StringIO):
    def isatty(self):
        return True


def _word(rng):
    return "".join(rng.choice("bcdfghjklmnpqrstvwxz") + rng.choice("aeiou") for _ in range(4)).capitalize()


def people(mod, count, start=0):
    import random

    importer = mod("importer")
    rng = random.Random(7)
    names = []
    while len(names) < start + count:
        name = f"{_word(rng)} {_word(rng)}"
        if name not in names:
            names.append(name)
    return [importer.Incoming(name=names[i], phones=[f"+1 202 555 {i % 10000:04d}"], details=[f"note {i}"]) for i in range(start, start + count)]


def counts(vault):
    with vault.read() as connection:
        return connection.execute("SELECT count(*) FROM cards").fetchone()[0], connection.execute("SELECT count(*) FROM changes WHERE undone_at IS NULL").fetchone()[0]


def test_batches_save_separately_and_undo_as_one(vault, mod, monkeypatch):
    saves = []
    original = vault._save
    monkeypatch.setattr(vault, "_save", lambda *a, **k: saves.append(1) or original(*a, **k))
    result = mod("importer").import_in_batches(vault, people(mod, 450), "test import", batch_size=200)
    assert (result.applied, result.total, result.stopped, result.summary.new) == (450, 450, None, 450)
    assert len(saves) == 3
    assert counts(vault) == (450, 1)
    assert mod("commands").handle("undo", platform="cli", vault=vault).startswith("Undone: imported from test import")
    assert counts(vault)[0] == 0


def test_import_that_stops_part_way_keeps_a_valid_store(vault, mod, monkeypatch):
    calls = {"n": 0}
    original = vault.write

    def flaky():
        calls["n"] += 1
        if calls["n"] == 3:
            raise mod("vault").Busy("simulated")
        return original()

    monkeypatch.setattr(vault, "write", flaky)
    result = mod("importer").import_in_batches(vault, people(mod, 500), "test import", batch_size=200)
    assert (result.applied, result.total) == (400, 500) and result.stopped is not None
    assert counts(vault) == (400, 1)
    name = people(mod, 400)[399].name
    assert name in mod("commands").handle(f'"{name}"', platform="cli", vault=vault)


def test_cli_reports_what_was_applied(vault, mod, monkeypatch, tmp_path):
    card = tmp_path / "many.vcf"
    card.write_text("".join(f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{p.name}\r\nTEL:+1 202 555 {i:04d}\r\nEND:VCARD\r\n" for i, p in enumerate(people(mod, 300))))
    calls = {"n": 0}
    original = vault.write

    def flaky():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk went away")
        return original()

    monkeypatch.setattr(vault, "write", flaky)
    out = Terminal()
    assert mod("cli").cmd_import(argparse.Namespace(path=str(card)), vault=vault, stdin=Terminal(), stdout=out) == 1
    assert out.getvalue().splitlines() == [
        "Imported. New: 200. Merged: 0. To review: 0. Unchanged: 0. Skipped: 0.",
        "The import stopped after 200 of 300 contacts. Those are saved, and /contacts undo removes them.",
    ]


def test_undo_during_import_stops_it(vault, mod, monkeypatch):
    original = vault.write
    calls = {"n": 0}

    def undo_after_first():
        calls["n"] += 1
        if calls["n"] == 2:
            mod("commands").handle("undo", platform="cli", vault=vault)
        return original()

    monkeypatch.setattr(vault, "write", undo_after_first)
    result = mod("importer").import_in_batches(vault, people(mod, 400), "test import", batch_size=200)
    assert result.applied == 200 and isinstance(result.stopped, mod("db").ChangeClosed)
    assert counts(vault)[0] == 0


def test_merges_still_work_across_batches(vault, mod):
    importer = mod("importer")
    first = people(mod, 250)
    again = [importer.Incoming(name="Someone Else", phones=["+1 202 555 0249"], details=["met at a party"])]
    result = importer.import_in_batches(vault, first + again, "test import", batch_size=200)
    assert (result.summary.new, result.summary.merged) == (250, 1)


def test_lookup_during_big_import_is_quick(vault, mod):
    commands = mod("commands")
    commands.handle("save Priya likes tea", platform="cli", vault=vault)
    contacts = people(mod, 5000)
    done = threading.Event()
    timings = []

    def run_import():
        mod("importer").import_in_batches(vault, contacts, "big import")
        done.set()

    worker = threading.Thread(target=run_import)
    worker.start()
    while not done.is_set():
        started = time.perf_counter()
        assert "likes tea" in commands.handle("priya tea", platform="cli", vault=vault)
        timings.append(time.perf_counter() - started)
    worker.join()
    print(f"\nLOOKUPS DURING IMPORT: {len(timings)}, slowest {max(timings) * 1000:.0f} ms, median {sorted(timings)[len(timings) // 2] * 1000:.0f} ms")
    assert len(timings) >= 3
    # A measurement, not a race: tests/benchmark.py reports the real number. The limit only catches
    # an import that holds the store for the whole run again.
    assert max(timings) < GENEROUS_LOOKUP_LIMIT


def test_first_undo_reverses_import_even_after_a_save_during_it(vault, mod, monkeypatch):
    commands = mod("commands")
    commands.handle("save Priya likes tea", platform="cli", vault=vault)
    original = vault.write
    calls = {"n": 0}

    def save_between_batches():
        calls["n"] += 1
        if calls["n"] == 2:
            commands.handle("save Priya likes jam", platform="cli", vault=vault)
        return original()

    monkeypatch.setattr(vault, "write", save_between_batches)
    result = mod("importer").import_in_batches(vault, people(mod, 450), "test import", batch_size=200)
    monkeypatch.setattr(vault, "write", original)
    assert result.applied == 450 and result.stopped is None
    assert commands.handle("undo", platform="cli", vault=vault) == "Undone: imported from test import."
    assert counts(vault)[0] == 1
    assert "likes jam" in commands.handle("priya jam", platform="cli", vault=vault)
    assert commands.handle("undo", platform="cli", vault=vault) == "Undone: saved to Priya."
    assert "likes jam" not in commands.handle("priya", platform="cli", vault=vault)


def test_save_to_an_imported_card_before_the_last_batch_keeps_undo_working(vault, mod, monkeypatch):
    importer, commands = mod("importer"), mod("commands")
    contacts = [importer.Incoming(name="Alice Moon", phones=["+1 202 555 0199"])] + people(mod, 399)
    original = vault.write
    calls = {"n": 0}

    def save_to_alice_before_last_batch():
        calls["n"] += 1
        if calls["n"] == 2:
            assert commands.handle('save "Alice Moon" likes tea', platform="cli", vault=vault).startswith("Saved to Alice Moon.")
        return original()

    monkeypatch.setattr(vault, "write", save_to_alice_before_last_batch)
    result = importer.import_in_batches(vault, contacts, "test import", batch_size=200)
    monkeypatch.setattr(vault, "write", original)
    assert result.applied == 400 and result.stopped is None
    assert commands.handle("undo", platform="cli", vault=vault) == "Undone: saved to Alice Moon."
    assert commands.handle("undo", platform="cli", vault=vault) == "Undone: imported from test import."
    assert counts(vault)[0] == 0
    assert commands.handle("undo", platform="cli", vault=vault) == "Nothing to undo."


def test_blocked_undo_changes_nothing_and_says_why(vault, mod):
    commands = mod("commands")
    commands.handle("save Zed likes tea", platform="cli", vault=vault)
    commands.handle("save Zed likes jam", platform="cli", vault=vault)
    with vault.write() as connection:
        first = connection.execute("SELECT min(id) FROM changes").fetchone()[0]
        connection.execute("UPDATE changes SET id=999 WHERE id=?", (first,))
    before = vault.store_path.read_bytes()
    assert commands.handle("undo", platform="cli", vault=vault) == "Can't undo saved to Zed: something saved later still uses a card it made. Nothing was changed."
    assert vault.store_path.read_bytes() == before
    assert "likes jam" in commands.handle("zed jam", platform="cli", vault=vault)
