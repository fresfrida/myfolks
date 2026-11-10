import os
import random
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

WORKER = str(Path(__file__).parent / "worker.py")


def set_value(vault, key, value):
    with vault.write() as connection:
        connection.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )


def get_value(vault, key):
    with vault.read() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None


def test_round_trip(vault):
    set_value(vault, "k", "a line")
    assert get_value(vault, "k") == "a line"


def test_plaintext_never_in_file(vault):
    set_value(vault, "k", "SECRET-PEANUT-WORDS")
    for path in [vault.store_path, *vault.version_files()]:
        assert b"SECRET-PEANUT-WORDS" not in path.read_bytes()
        assert b"SQLite format" not in path.read_bytes()


def test_store_file_is_private(vault):
    assert stat.S_IMODE(vault.store_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(vault.keys.file_path.stat().st_mode) == 0o600


def test_fresh_nonce_each_save(vault, mod):
    seen = set()
    for number in range(5):
        set_value(vault, "k", "same")
        seen.add(vault.store_path.read_bytes())
        set_value(vault, f"n{number}", "x")
    assert len(seen) == 5


def test_read_does_not_save(vault):
    before = vault.store_path.read_bytes()
    get_value(vault, "k")
    assert vault.store_path.read_bytes() == before


def test_failed_write_saves_nothing(vault):
    before = vault.store_path.read_bytes()
    with pytest.raises(RuntimeError):
        with vault.write() as connection:
            connection.execute("INSERT INTO settings(key,value) VALUES('a','b')")
            raise RuntimeError("boom")
    assert vault.store_path.read_bytes() == before


def test_wrong_device_key_refused_and_untouched(vault, mod):
    set_value(vault, "k", "v")
    before = vault.store_path.read_bytes()
    vault.keys.create()
    with pytest.raises(mod("vault").Refused):
        get_value(vault, "k")
    with pytest.raises(mod("vault").Refused):
        set_value(vault, "k", "other")
    assert vault.store_path.read_bytes() == before


def test_missing_device_key_refused(vault, mod):
    vault.keys.file_path.unlink()
    with pytest.raises(mod("vault").Refused):
        get_value(vault, "k")


@pytest.mark.parametrize("where", ["magic", "version", "header", "nonce", "body", "tag"])
def test_tamper_refused_and_untouched(vault, mod, where):
    set_value(vault, "k", "v")
    blob = bytearray(vault.store_path.read_bytes())
    header_length = int.from_bytes(blob[5:9], "big")
    body = 9 + header_length
    position = {"magic": 0, "version": 4, "header": 20, "nonce": body + 1, "body": body + 40, "tag": len(blob) - 1}[where]
    blob[position] ^= 0x01
    vault.store_path.write_bytes(bytes(blob))
    with pytest.raises(mod("vault").Refused):
        get_value(vault, "k")
    assert vault.store_path.read_bytes() == bytes(blob)


def test_truncated_file_refused(vault, mod):
    vault.store_path.write_bytes(vault.store_path.read_bytes()[:6])
    with pytest.raises(mod("vault").Refused):
        get_value(vault, "k")


def test_recovery_on_new_device(vault, tmp_path, mod):
    set_value(vault, "k", "kept")
    vault.keys.file_path.unlink()
    vault.recover(vault.recovery_code.lower().replace("-", " "))
    assert get_value(vault, "k") == "kept"


def test_wrong_code_refused_and_untouched(vault, mod):
    before = vault.store_path.read_bytes()
    key_before = vault.keys.file_path.read_bytes()
    wrong = "AAAA-" * 7 + "AAAA"
    with pytest.raises(mod("vault").Refused):
        vault.recover(wrong)
    with pytest.raises(mod("vault").Refused):
        vault.recover("short")
    assert vault.store_path.read_bytes() == before
    assert vault.keys.file_path.read_bytes() == key_before


def test_setup_twice_refused(vault, mod):
    with pytest.raises(mod("vault").AlreadySetUp):
        vault.setup()


def test_not_set_up(tmp_path, mod):
    instance = mod("vault").Vault(tmp_path / "x", keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    with pytest.raises(mod("vault").NotSetUp):
        with instance.read():
            pass


def test_keeps_last_seven_versions_in_order(vault):
    for number in range(12):
        set_value(vault, "counter", str(number))
    files = vault.version_files()
    assert len(files) == 7
    current = vault.store_path.read_bytes()
    seen = []
    for path in files:
        vault.store_path.write_bytes(path.read_bytes())
        seen.append(get_value(vault, "counter"))
    vault.store_path.write_bytes(current)
    assert seen == ["4", "5", "6", "7", "8", "9", "10"]


def test_keychain_used_when_real(tmp_path, mod):
    class FakeKeyring:
        def __init__(self):
            self.items = {}

        def set_password(self, service, account, value):
            self.items[(service, account)] = value

        def get_password(self, service, account):
            return self.items.get((service, account))

    keyring = FakeKeyring()
    keys = mod("device_key").DeviceKeys(tmp_path, keyring_module=keyring)
    instance = mod("vault").Vault(tmp_path, keys=keys)
    instance.setup()
    assert not keys.file_path.exists()
    assert keyring.items
    with instance.write() as connection:
        connection.execute("INSERT INTO settings(key,value) VALUES('a','b')")


def test_not_a_real_keychain_is_ignored(mod):
    class Fail:
        pass

    Fail.__module__ = "keyring.backends.fail"
    assert mod("device_key")._is_os_keychain(Fail()) is False


def test_kill_during_saves_leaves_old_or_new(vault):
    random.seed(7)
    last_seen = -1
    for _round in range(25):
        process = subprocess.Popen(
            [sys.executable, WORKER, "spin", str(vault.directory), "x", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        assert process.stdout.readline().strip() != ""
        time.sleep(random.uniform(0.0, 0.08))
        process.send_signal(signal.SIGKILL)
        output = process.stdout.read().split()
        process.wait()
        value = int(get_value(vault, "counter"))
        reported = None
        for token in output:
            reported = int(token)
        assert value >= 0
        if reported is not None:
            assert value in (reported, reported + 1)
        last_seen = value
    assert last_seen >= 0


def test_two_processes_writing_lose_nothing(vault):
    runs = [
        subprocess.Popen([sys.executable, WORKER, "append", str(vault.directory), label, "40"])
        for label in ("a", "b", "c")
    ]
    assert [run.wait(timeout=120) for run in runs] == [0, 0, 0]
    with vault.read() as connection:
        assert connection.execute("SELECT count(*) FROM settings WHERE key LIKE '%-%'").fetchone()[0] == 120


def test_busy_when_lock_held_too_long(vault, mod):
    other = mod("vault").Vault(vault.directory, keys=vault.keys, lock_timeout=0.05)
    with vault.read():
        with pytest.raises(mod("vault").Busy):
            with other.read():
                pass


def test_cli_setup_needs_a_terminal(tmp_path, mod, capsys):
    class NotATerminal:
        def isatty(self):
            return False

    assert mod("cli").cmd_setup(None, stdout=NotATerminal()) == 1


def test_cli_setup_shows_code_once_and_recover(tmp_path, mod):
    import io

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    instance = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    out = Terminal()
    assert mod("cli").cmd_setup(None, vault=instance, stdout=out) == 0
    code = [line for line in out.getvalue().splitlines() if line.count("-") == 7][0]
    assert code.encode() not in instance.store_path.read_bytes()
    assert mod("cli").cmd_recover(None, vault=instance, read_code=lambda _prompt: "A" * 32, stdout=out) == 1
    assert mod("cli").cmd_recover(None, vault=instance, read_code=lambda _prompt: code, stdout=out) == 0
    with instance.read() as connection:
        assert connection.execute("SELECT count(*) FROM cards").fetchone()[0] == 0
