"""What setup, the locked message and hermes myfolks backup tell the user about where MyFolks keeps
what they save, what the recovery code is for, and how to back up."""

import argparse
import io
import os
import re
import stat
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PLUGIN_JS = (ROOT / "desktop" / "plugin.js").read_text()
PASS = "correct horse battery"
CODE = re.compile(r"[A-Z2-7]{4}(?:-[A-Z2-7]{4}){7}")
NOW = datetime(2026, 11, 11, 21, 30, 5)
DEFAULT_NAME = "myfolks-backup-2026-11-11-213005.mfbk"


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def fresh(tmp_path, mod):
    return mod("vault").Vault(tmp_path / "store", keys=mod("device_key").DeviceKeys(tmp_path / "store", use_keychain=False))


def test_terminal_setup_prints_exactly_the_approved_screen(fresh, mod):
    out = Terminal()
    assert mod("cli").cmd_setup(None, vault=fresh, stdout=out) == 0
    code = CODE.search(out.getvalue()).group(0)
    assert out.getvalue() == (
        "MyFolks is ready.\n"
        "Next, bring in your contacts: send /myfolks sync to use your Google contacts, or run hermes myfolks import <file>.\n"
        "MyFolks keeps what you save only in your Hermes folder, on the computer that runs Hermes. If you use it from a chat app like Telegram, that app also keeps a copy of the chat. Your address book is separate, and MyFolks never changes it.\n"
        "\n"
        "Your recovery code. It is shown once. Keep it somewhere safe:\n"
        f"{code}\n"
        "You need it if MyFolks stops opening, and to back up or export.\n"
        "\n"
        "Back up what you've saved, in case you lose that computer:\n"
        "  hermes myfolks backup\n"
        "You'll get one file, locked with a passphrase you choose. Keep it somewhere else, like a USB drive.\n"
        "\n"
        "About Hermes's own backups\n"
        "If you also run hermes backup, those files include MyFolks.\n"
    )
    assert "password" not in out.getvalue().lower()


def test_desktop_setup_screen_has_the_same_text():
    for line in [
        "setupDone: 'MyFolks is ready.',",
        "setupStoredHere: 'MyFolks keeps what you save only in your Hermes folder, on the computer that runs Hermes. If you use it from a chat app like Telegram, that app also keeps a copy of the chat. Your address book is separate, and MyFolks never changes it.',",
        "setupCodeIntro: 'Your recovery code. It is shown once. Keep it somewhere safe:',",
        "setupCodePurpose: 'You need it if MyFolks stops opening, and to back up or export.',",
        "setupBackupIntro: 'Back up what you’ve saved, in case you lose that computer:',",
        "setupBackupCommand: 'hermes myfolks backup',",
        "setupBackupResult: 'You’ll get one file, locked with a passphrase you choose. Keep it somewhere else, like a USB drive.',",
        "setupHermesBackupHeading: 'About Hermes’s own backups',",
        "setupHermesBackupNote: 'If you also run hermes backup, those files include MyFolks.',",
    ]:
        assert line in PLUGIN_JS


def test_desktop_setup_screen_keeps_the_terminal_order_and_ends_with_the_button():
    panel = PLUGIN_JS[PLUGIN_JS.index("function SetupPanel"):PLUGIN_JS.index("function Page(")]
    order = [
        "COPY.setupDone", "COPY.setupStoredHere", "COPY.setupCodeIntro", "RecoveryCode, { children: step.code }",
        "COPY.setupCodePurpose", "COPY.setupBackupIntro", "Command, { children: COPY.setupBackupCommand }",
        "COPY.setupBackupResult", "'text-sm font-medium', children: COPY.setupHermesBackupHeading", "COPY.setupHermesBackupNote",
        "COPY.savedIt",
    ]
    positions = [panel.index(item) for item in order]
    assert "password" not in panel.lower()
    assert "password" not in "".join(line for line in PLUGIN_JS.splitlines() if line.strip().startswith("setup")).lower()
    assert positions == sorted(positions)
    assert panel.count("jsx(Button") == 2  # the set-up button before, and only "I've saved it" on the code screen


def test_old_loss_sentence_is_gone_from_every_file():
    old = "lose both " + "this device"
    skip = {".git", "docs", "plan", "__pycache__"}
    for path in ROOT.rglob("*"):
        if path.is_file() and not skip.intersection(path.relative_to(ROOT).parts) and path.suffix in {".py", ".js", ".md", ".yaml", ".json"}:
            assert old not in path.read_text(encoding="utf-8", errors="ignore"), path


def test_locked_message_says_how_to_unlock(mod):
    assert mod("messages").LOCKED == "MyFolks can't open its data. Nothing was changed. To unlock it with your recovery code, run: hermes myfolks recover"
    assert "lockedBody: 'Nothing was changed. To unlock it with your recovery code, run this in your terminal.'," in PLUGIN_JS
    assert "lockedCommand: 'hermes myfolks recover'," in PLUGIN_JS
    for text in (mod("messages").LOCKED, PLUGIN_JS):
        assert "moved to a new device" not in text


def test_locked_store_answers_with_the_locked_message(vault, mod):
    vault.keys.file_path.unlink()
    assert mod("commands").handle("priya", platform="cli", vault=vault) == mod("messages").LOCKED


# hermes myfolks backup: where the file goes


def _backup(mod, vault, output, now=NOW):
    cli = mod("cli")
    out = Terminal()
    secret = lambda prompt: vault.recovery_code if prompt == "Recovery code: " else PASS  # noqa: E731
    real = cli.backup_path
    cli.backup_path = lambda value: real(value, now=now)
    try:
        code = cli.cmd_backup(argparse.Namespace(output=output), vault=vault, read_secret=secret, stdin=Terminal(), stdout=out)
    finally:
        cli.backup_path = real
    return code, out.getvalue()


def _done(path):
    return f"Backup saved to {path}. Keep it somewhere other than this computer. Keep the passphrase safe: without it, this file can't be opened.\n"


def test_no_output_writes_the_default_name_in_the_home_folder(vault, mod, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    code, output = _backup(mod, vault, None)
    target = home / DEFAULT_NAME
    assert code == 0 and target.exists() and output == _done(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_file_is_used_as_given(vault, mod, tmp_path):
    target = tmp_path / "mine.mfbk"
    code, output = _backup(mod, vault, str(target))
    assert code == 0 and target.exists() and output == _done(target)


def test_a_folder_gets_the_default_name(vault, mod, tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    code, output = _backup(mod, vault, str(folder))
    assert code == 0 and [p.name for p in folder.iterdir()] == [DEFAULT_NAME] and output == _done(folder / DEFAULT_NAME)


def test_a_missing_folder_ending_in_a_slash_is_made_and_gets_the_default_name(vault, mod, tmp_path):
    folder = tmp_path / "new" / "folder"
    code, output = _backup(mod, vault, f"{folder}/")
    assert code == 0 and [p.name for p in folder.iterdir()] == [DEFAULT_NAME] and output == _done(folder / DEFAULT_NAME)


def test_missing_parent_folders_are_created(vault, mod, tmp_path):
    target = tmp_path / "new" / "deeper" / "b.mfbk"
    code, output = _backup(mod, vault, str(target))
    assert code == 0 and target.exists() and output == _done(target)


def test_a_relative_path_is_printed_in_full(vault, mod, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, output = _backup(mod, vault, "rel.mfbk")
    assert code == 0 and output == _done((tmp_path / "rel.mfbk").resolve())


def test_an_existing_file_is_refused_and_kept(vault, mod, tmp_path):
    target = tmp_path / "b.mfbk"
    target.write_text("keep me")
    code, output = _backup(mod, vault, str(target))
    assert code == 1 and output == "That file already exists. Choose a new name. Nothing was written.\n"
    assert target.read_text() == "keep me"


def test_an_existing_default_name_in_a_folder_is_refused(vault, mod, tmp_path):
    (tmp_path / DEFAULT_NAME).write_text("keep me")
    code, _output = _backup(mod, vault, str(tmp_path))
    assert code == 1 and (tmp_path / DEFAULT_NAME).read_text() == "keep me"


def test_a_file_in_the_way_of_a_folder_prints_one_line_and_writes_nothing(vault, mod, tmp_path):
    (tmp_path / "taken").write_text("a file, not a folder")
    code, output = _backup(mod, vault, str(tmp_path / "taken" / "inner" / "b.mfbk"))
    assert code == 1 and output == "MyFolks can't write a file there. Nothing was written.\n"
    assert (tmp_path / "taken").read_text() == "a file, not a folder"


def test_a_write_that_fails_part_way_leaves_no_file(vault, mod, tmp_path, monkeypatch):
    def full_disk(_fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", full_disk)
    code, output = _backup(mod, vault, str(tmp_path / "b.mfbk"))
    assert code == 1 and output == "MyFolks can't write a file there. Nothing was written.\n"
    assert not (tmp_path / "b.mfbk").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores folder permissions")
def test_an_unwritable_place_prints_one_line_and_writes_nothing(vault, mod, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        code, output = _backup(mod, vault, str(locked / "inner" / "b.mfbk"))
    finally:
        locked.chmod(0o700)
    assert code == 1 and output == "MyFolks can't write a file there. Nothing was written.\n"
    assert list(locked.iterdir()) == []


def test_backup_help_names_the_default(mod):
    parser = argparse.ArgumentParser()
    mod("cli").setup_parser(parser)
    assert parser.parse_args(["backup"]).output is None
    assert parser.parse_args(["backup", "-o", "x"]).output == "x"
    assert parser.parse_args(["backup", "--output", "x"]).output == "x"
    with pytest.raises(SystemExit):
        parser.parse_args(["restore"])
    with pytest.raises(SystemExit):
        parser.parse_args(["export"])


def test_restore_into_a_new_store_shows_the_code_with_what_it_is_for(vault, mod, tmp_path, fresh):
    target = tmp_path / "b.mfbk"
    _backup(mod, vault, str(target))
    out = Terminal()
    assert mod("cli").cmd_restore(argparse.Namespace(path=str(target)), vault=fresh, read_secret=lambda _p: PASS, stdin=Terminal(), stdout=out) == 0
    lines = out.getvalue().splitlines()
    assert lines[1] == "Your recovery code. It is shown once. Keep it somewhere safe:" and CODE.fullmatch(lines[2])
    assert lines[3] == "You need it if MyFolks stops opening, and to back up or export."
    assert "after you restore a Hermes backup" not in out.getvalue()


def test_recover_says_it_opens_on_this_computer(vault, mod):
    out = Terminal()
    vault.keys.file_path.unlink()
    assert mod("cli").cmd_recover(None, vault=vault, read_code=lambda _prompt: vault.recovery_code, stdout=out) == 0
    assert out.getvalue() == "Recovered. MyFolks opens on this computer again.\n"


def test_no_text_says_this_device(mod):
    texts = [value for name, value in vars(mod("messages")).items() if isinstance(value, str) and name.isupper()]
    texts.append(mod("messages").backup_done("/x"))
    assert not [text for text in texts if "device" in text.lower()]
    assert "this device" not in PLUGIN_JS.lower()


def test_no_setup_or_restore_text_promises_a_hermes_backup_needs_the_code(mod):
    texts = [value for name, value in vars(mod("messages")).items() if isinstance(value, str) and name.isupper()]
    assert not [text for text in texts if "after you restore a Hermes backup" in text]
    assert "after you restore a Hermes backup" not in PLUGIN_JS
