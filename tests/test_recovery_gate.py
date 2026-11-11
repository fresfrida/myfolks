"""Export, backup, restore and pair need the recovery code, even from a pseudo-terminal like the one
Hermes's terminal tool gives the AI."""
import argparse
import inspect
import io
import os
import pty
import select
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SENSITIVE = ["export", "backup", "restore", "pair"]


class Terminal(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def stored(vault, mod):
    mod("commands").handle("save Priya is allergic to peanuts", platform="cli", vault=vault)
    return vault


def _args(tmp_path, command, stored, mod):
    if command == "restore":
        backup = tmp_path / "in.mfbk"
        backup.write_bytes(mod("backup").seal(stored.database_bytes(), "correct horse battery"))
        return argparse.Namespace(path=str(backup))
    return argparse.Namespace(path=str(tmp_path / f"out-{command}"))


@pytest.mark.parametrize("command", SENSITIVE)
@pytest.mark.parametrize("typed", ["", "WRONG-CODE", "AAAA-BBBB-CCCC-DDDD-EEEE-FFFF-GGGG-HHHH"])
def test_refuses_without_the_right_code(stored, mod, tmp_path, command, typed):
    before = stored.store_path.read_bytes()
    asked = []
    out = Terminal()

    def secret(prompt):
        asked.append(prompt)
        return typed if prompt == "Recovery code: " else "correct horse battery"

    handler = getattr(mod("cli"), f"cmd_{command}")
    extra = {"read_line": lambda _p: pytest.fail("asked to confirm")} if "read_line" in inspect.signature(handler).parameters else {}
    result = handler(_args(tmp_path, command, stored, mod), vault=stored, read_secret=secret, stdin=Terminal(), stdout=out, **extra)
    assert result == 1
    assert asked == ["Recovery code: "]
    assert out.getvalue().strip() == "That code doesn't open MyFolks. Nothing was changed."
    assert stored.store_path.read_bytes() == before
    assert not (tmp_path / f"out-{command}").exists()
    with stored.read() as connection:
        assert mod("db").get_setting(connection, "pairing_code") in (None, "")


@pytest.mark.parametrize("command", ["export", "pair"])
def test_right_code_lets_it_run(stored, mod, tmp_path, command):
    out = Terminal()
    handler = getattr(mod("cli"), f"cmd_{command}")
    result = handler(_args(tmp_path, command, stored, mod), vault=stored, read_secret=lambda _p: stored.recovery_code, read_line=lambda _p: "EXPORT", stdin=Terminal(), stdout=out)
    assert result == 0, out.getvalue()


def _read_available(fd) -> bytes:
    try:
        return os.read(fd, 4096)
    except OSError:  # the child closed its side
        return b""


def _run_in_pty(args, answers, timeout=120):
    """Run the command in a pseudo-terminal, answer prompts, and read until the child has exited."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, str(HERE / "pty_cli.py"), *args])
    output, pending, deadline, status = b"", list(answers), time.monotonic() + timeout, None
    try:
        while status is None:
            if time.monotonic() > deadline:
                os.kill(pid, 9)
                pytest.fail(f"command did not finish: {output.decode(errors='replace')}")
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                chunk = _read_available(fd)
                output += chunk
                if pending and output.rstrip().endswith(b":"):
                    os.write(fd, (pending.pop(0) + "\n").encode())
            done, raw = os.waitpid(pid, os.WNOHANG)
            if done:
                status = raw
        while True:
            ready, _, _ = select.select([fd], [], [], 0.1)
            chunk = _read_available(fd) if ready else b""
            if not chunk:
                break
            output += chunk
    finally:
        os.close(fd)
    return os.waitstatus_to_exitcode(status), output.decode(errors="replace")


@pytest.mark.parametrize("command", SENSITIVE)
def test_pseudo_terminal_without_the_code_is_refused(stored, mod, tmp_path, command):
    """What an AI with Hermes's terminal tool would see: a real pseudo-terminal, typing EXPORT and a passphrase."""
    before = stored.store_path.read_bytes()
    target = _args(tmp_path, command, stored, mod).path
    code, output = _run_in_pty([str(stored.directory), command, target], ["EXPORT", "EXPORT", "EXPORT"])
    assert code == 1, output
    assert "Recovery code:" in output and "That code doesn't open MyFolks. Nothing was changed." in output
    assert "Type EXPORT" not in output and "passphrase" not in output.lower()
    assert stored.store_path.read_bytes() == before
    assert not (tmp_path / f"out-{command}").exists()


def test_pseudo_terminal_with_the_code_works(stored, mod, tmp_path):
    target = tmp_path / "out-export"
    code, output = _run_in_pty([str(stored.directory), "export", str(target)], [stored.recovery_code, "EXPORT"])
    assert code == 0, output
    assert "allergic to peanuts" in target.read_text()
