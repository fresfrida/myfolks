from loader import save_hidden
import argparse
import io
import json
import stat

import pytest

PASS = "correct horse battery"


class Terminal(io.StringIO):
    def isatty(self):
        return True


class NotTerminal(io.StringIO):
    def isatty(self):
        return False


@pytest.fixture
def filled(vault, mod):
    handle = mod("commands").handle
    handle("save Priya is allergic to peanuts", platform="cli", vault=vault)
    save_hidden(vault, "Priya sees a therapist")
    return vault


@pytest.fixture
def cli(mod):
    return mod("cli")


def args(path):
    return argparse.Namespace(path=str(path))


def run_backup(cli, vault, path, secret=PASS):
    out = Terminal()
    return cli.cmd_backup(args(path), vault=vault, read_secret=lambda _p: secret, stdin=Terminal(), stdout=out), out.getvalue()


def run_restore(cli, vault, path, secret=PASS, typed=None):
    out = Terminal()
    code = cli.cmd_restore(args(path), vault=vault, read_secret=lambda _p: secret, read_line=(lambda _p: typed) if typed is not None else _fail, stdin=Terminal(), stdout=out)
    return code, out.getvalue()


def _fail(_prompt):
    raise AssertionError("should not ask")


def fresh(tmp_path, mod, name):
    return mod("vault").Vault(tmp_path / name, keys=mod("device_key").DeviceKeys(tmp_path / name, use_keychain=False))


def lookup(mod, vault, text):
    return mod("commands").handle(text, platform="cli", vault=vault)


def test_round_trip_into_new_store(filled, cli, tmp_path, mod):
    path = tmp_path / "b.mfbk"
    assert run_backup(cli, filled, path)[0] == 0
    target = fresh(tmp_path, mod, "new")
    code, output = run_restore(cli, target, path)
    assert code == 0 and "Restored." in output and "recovery code" in output
    assert "allergic to peanuts" in lookup(mod, target, "priya allergic")
    assert "therapist" in lookup(mod, target, "priya therapist")


def test_new_store_recovery_code_works(filled, cli, tmp_path, mod):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    target = fresh(tmp_path, mod, "new")
    code_line = [l for l in run_restore(cli, target, path)[1].splitlines() if l.count("-") == 7][0]
    target.keys.file_path.unlink()
    target.recover(code_line)
    assert "allergic" in lookup(mod, target, "priya allergic")


def test_backup_file_is_encrypted_and_private(filled, cli, tmp_path):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    blob = path.read_bytes()
    assert b"peanuts" not in blob and b"SQLite format" not in blob
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_no_plaintext_temp_files(filled, cli, tmp_path):
    folder = tmp_path / "out"
    folder.mkdir()
    run_backup(cli, filled, folder / "b.mfbk")
    assert [p.name for p in folder.iterdir()] == ["b.mfbk"]


def test_wrong_passphrase_refused(filled, cli, tmp_path, mod):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    target = fresh(tmp_path, mod, "new")
    code, output = run_restore(cli, target, path, secret="not the passphrase")
    assert code == 1 and "doesn't open" in output and not target.exists()


@pytest.mark.parametrize("position", [0, 6, 20, -1])
def test_tampered_backup_refused(filled, cli, tmp_path, mod, position):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    blob = bytearray(path.read_bytes())
    blob[position] ^= 1
    path.write_bytes(bytes(blob))
    target = fresh(tmp_path, mod, "new")
    assert run_restore(cli, target, path)[0] == 1 and not target.exists()


def test_refuses_to_overwrite_without_confirmation(filled, cli, tmp_path, mod):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    mod("commands").handle("save Marco likes jazz", platform="cli", vault=filled)
    before = filled.store_path.read_bytes()
    code, output = run_restore(cli, filled, path, typed="no")
    assert code == 1 and "Nothing was changed." in output and filled.store_path.read_bytes() == before


def test_overwrite_after_typed_confirmation(filled, cli, tmp_path, mod):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    mod("commands").handle("save Marco likes jazz", platform="cli", vault=filled)
    assert run_restore(cli, filled, path, typed="REPLACE")[0] == 0
    assert lookup(mod, filled, "marco") == "Nothing saved about that."
    assert "allergic" in lookup(mod, filled, "priya allergic")


def test_restore_into_empty_store_needs_no_confirmation(filled, cli, tmp_path, mod):
    path = tmp_path / "b.mfbk"
    run_backup(cli, filled, path)
    target = fresh(tmp_path, mod, "empty")
    target.setup()
    code, output = run_restore(cli, target, path)
    assert code == 0 and "recovery code" not in output
    assert "allergic" in lookup(mod, target, "priya allergic")


def test_backup_refuses_existing_file_and_short_passphrase(filled, cli, tmp_path):
    path = tmp_path / "b.mfbk"
    path.write_text("keep me")
    assert run_backup(cli, filled, path)[0] == 1 and path.read_text() == "keep me"
    assert run_backup(cli, filled, tmp_path / "c.mfbk", secret="short")[0] == 1


def test_backup_needs_matching_passphrase(filled, cli, tmp_path):
    answers = iter([PASS, "something else"])
    out = Terminal()
    assert cli.cmd_backup(args(tmp_path / "x"), vault=filled, read_secret=lambda _p: next(answers), stdin=Terminal(), stdout=out) == 1
    assert not (tmp_path / "x").exists()


@pytest.mark.parametrize("name", ["cmd_backup", "cmd_restore", "cmd_export"])
def test_terminal_only(filled, cli, tmp_path, name):
    assert getattr(cli, name)(args(tmp_path / "x"), vault=filled, stdin=NotTerminal(), stdout=NotTerminal()) == 1


def test_export_needs_typed_confirmation(filled, cli, tmp_path):
    out = Terminal()
    path = tmp_path / "e.json"
    assert cli.cmd_export(args(path), vault=filled, read_line=lambda _p: "no", stdin=Terminal(), stdout=out) == 1
    assert not path.exists()


def test_export_writes_everything_private_file(filled, cli, tmp_path):
    out = Terminal()
    path = tmp_path / "e.json"
    assert cli.cmd_export(args(path), vault=filled, read_line=lambda _p: "EXPORT", stdin=Terminal(), stdout=out) == 0
    document = json.loads(path.read_text())
    lines = document["cards"][0]["lines"]
    assert [l["text"] for l in lines] == ["is allergic to peanuts", "sees a therapist"] and lines[1]["private"] is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_export_refuses_existing_file(filled, cli, tmp_path):
    path = tmp_path / "e.json"
    path.write_text("keep")
    assert cli.cmd_export(args(path), vault=filled, read_line=_fail, stdin=Terminal(), stdout=Terminal()) == 1
    assert path.read_text() == "keep"
