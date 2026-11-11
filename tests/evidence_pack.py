#!/usr/bin/env python3
"""MyFolks evidence pack: runs the published checks on made-up data and prints the real results.

Usage, from the repo root, with a Python that has `cryptography`:
    python3 tests/evidence_pack.py
Exits non-zero if a safety check fails. The search score is reported, including every miss.
"""

import json
import os
import random
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from loader import load  # noqa: E402

load()
import importlib  # noqa: E402

commands = importlib.import_module("myfolks.commands")
device_key = importlib.import_module("myfolks.device_key")
owner = importlib.import_module("myfolks.owner")
vault_module = importlib.import_module("myfolks.vault")
ai_tool = importlib.import_module("myfolks.ai_tool")
desktop_service = importlib.import_module("myfolks.desktop_service")

WORKER = str(HERE / "worker.py")
NOTHING = "Nothing saved about that."
NO_ONE = "No one called "


def found_nothing(reply):
    """No answer: "Nothing saved about that" (with or without "yet") or "No one called", whatever
    next-step hint follows on the lines below."""
    first = reply.split("\n")[0]
    return first.startswith("Nothing saved about that") or first.startswith(NO_ONE)
REFUSED = "MyFolks isn't available here."
failures = []


def report(name, passed, detail=""):
    print(f"  {'PASS' if passed else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    if not passed:
        failures.append(name)


_temp = tempfile.TemporaryDirectory(prefix="myfolks-evidence-")


def new_vault():
    directory = Path(tempfile.mkdtemp(dir=_temp.name))
    vault = vault_module.Vault(directory, keys=device_key.DeviceKeys(directory, use_keychain=False))
    vault.recovery_code = vault.setup()
    return vault


def terminal(vault, text, answer=None):
    return commands.handle(text, platform="cli", vault=vault, ask=answer)


def set_counter(vault, value):
    with vault.write() as connection:
        connection.execute(
            "INSERT INTO settings(key,value) VALUES('counter',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,)
        )


def get_counter(vault):
    with vault.read() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key='counter'").fetchone()
        return row[0] if row else None


def is_unsure(reply):
    return reply.split("\n")[0].endswith(" · not sure")


def search_outcome(item, reply):
    expect, find = item["expect"], item.get("find", "")
    if expect == "ask":
        return reply.startswith(find) and '"' not in reply.split("To see it")[0]
    if expect == "direct":
        return not is_unsure(reply) and find in reply and not found_nothing(reply)
    if expect == "related":
        return is_unsure(reply) and find in reply
    if expect == "nothing":
        return found_nothing(reply)
    if expect == "not_direct":
        return is_unsure(reply) or found_nothing(reply)
    return find in reply.split("\n")[0]


def check_search():
    print("\n1. Search test set (made-up questions)")
    data = json.loads((HERE / "search_set.json").read_text())
    vault = new_vault()
    for line in data["setup"]:
        terminal(vault, line)
    misses, wrong_direct = [], []
    for item in data["questions"]:
        choose = item.get("choose")

        def ask(_question, choices):
            return next((c["value"] for c in choices if choose and choose in c["label"]), None)

        reply = commands.handle(item["q"], platform="cli", ask=ask, vault=vault)
        if not search_outcome(item, reply):
            misses.append((item, reply))
            if item["expect"] in ("nothing", "not_direct") and not is_unsure(reply) and not found_nothing(reply):
                wrong_direct.append(item["q"])
    total = len(data["questions"])
    print(f"  Score: {total - len(misses)}/{total} correct, {len(misses)} misses")
    for item, reply in misses:
        print(f"  MISS  expected {item['expect']}: {item['q']!r} -> {reply.splitlines()[0]!r}")
    report("no unanswerable question got a direct answer", not wrong_direct, ", ".join(wrong_direct))


def check_crash():
    print("\n2. Crash during save (process killed repeatedly)")
    vault = new_vault()
    random.seed(7)
    rounds, bad = 25, 0
    for _round in range(rounds):
        process = subprocess.Popen(
            [sys.executable, WORKER, "spin", str(vault.directory), "x", "0"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        process.stdout.readline()
        time.sleep(random.uniform(0.0, 0.08))
        process.send_signal(signal.SIGKILL)
        printed = process.stdout.read().split()
        process.wait()
        try:
            value = int(get_counter(vault))
        except Exception:
            bad += 1
            continue
        if printed and value not in (int(printed[-1]), int(printed[-1]) + 1):
            bad += 1
    report("file was always the old or the new version", bad == 0, f"{rounds} kills, {bad} bad")


def check_writers():
    print("\n3. Two writers at once")
    vault = new_vault()
    runs = [subprocess.Popen([sys.executable, WORKER, "append", str(vault.directory), label, "40"]) for label in ("a", "b", "c")]
    codes = [run.wait(timeout=180) for run in runs]
    with vault.read() as connection:
        saved = connection.execute("SELECT count(*) FROM settings WHERE key LIKE '%-%'").fetchone()[0]
    report("nothing lost", codes == [0, 0, 0] and saved == 120, f"3 processes, 40 saves each, {saved} of 120 kept")


def refused(action, error):
    try:
        action()
    except error:
        return True
    return False


def check_keys():
    print("\n4. Wrong key and tampered file")
    vault = new_vault()
    set_counter(vault, "kept")
    before = vault.store_path.read_bytes()
    vault.keys.create()
    report("wrong device key refused", refused(lambda: get_counter(vault), vault_module.Refused))
    report("file untouched after refusal", vault.store_path.read_bytes() == before)
    report("wrong recovery code refused", refused(lambda: vault.recover("AAAA-" * 7 + "AAAA"), vault_module.Refused))
    vault.recover(vault.recovery_code)
    report("correct recovery code opens it", get_counter(vault) == "kept")
    blob = bytearray(vault.store_path.read_bytes())
    results = []
    for position in (0, 4, 20, len(blob) // 2, len(blob) - 1):
        damaged = bytearray(blob)
        damaged[position] ^= 1
        vault.store_path.write_bytes(bytes(damaged))
        results.append(refused(lambda: get_counter(vault), vault_module.Refused))
    vault.store_path.write_bytes(bytes(blob))
    report("tampered file refused, never garbage", all(results), f"{len(results)} positions")
    report("no plaintext in the file", b"SQLite format" not in bytes(blob) and b"kept" not in bytes(blob))


def sender(user_id="111", chat_type="dm"):
    return SimpleNamespace(user_id=user_id, chat_type=chat_type, is_bot=False)


def check_owner():
    print("\n5. Non-owner and group chat")
    vault = new_vault()
    terminal(vault, "save Priya likes tea")
    owner.allowed_users = lambda platform: ({"111"}, False)

    def chat(text, source):
        return commands.handle(text, platform="telegram", source=source, vault=vault)

    report("owner in a private chat is answered", "likes tea" in chat("priya tea", sender()))
    report("someone else is refused", chat("priya tea", sender("222")) == REFUSED)
    report("group chat is refused, even for the owner", chat("priya tea", sender(chat_type="group")) == REFUSED)
    report("missing sender is refused", chat("priya tea", sender(user_id=None)) == REFUSED)


def check_wrong_person():
    print("\n6. Wrong-person rule (only an exact name opens a card)")
    vault = new_vault()
    terminal(vault, "save Briya is allergic to shellfish")
    reply = terminal(vault, "priya allergy")
    report("near name shows no details", reply.startswith("Did you mean Briya?") and "shellfish" not in reply)
    chosen = terminal(vault, "priya allergy", answer=lambda _q, choices: choices[0]["value"])
    report("choosing the card then shows it", "shellfish" in chosen)
    terminal(vault, "save --new Priya likes tea")
    report("exact name opens with no question", terminal(vault, "priya", answer=lambda *_a: "cancel").startswith("Priya\n"))
    report("Desktop route shows no details for a near name", "shellfish" not in str(desktop_service.find("bryia", vault)))
    tool = json.loads(ai_tool.handle({"action": "lookup", "question": "prya tea"}, vault=vault, session=("cli", None)))
    report("AI tool treats a near name as no match", tool == {"status": "nothing", "matches": []})


def main():
    print("MyFolks evidence pack. All data is made up and deleted with the temp folders.")
    for check in (check_search, check_crash, check_writers, check_keys, check_owner, check_wrong_person):
        check()
    print(f"\nSafety checks failed: {len(failures)}")
    for name in failures:
        print(f"  {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
