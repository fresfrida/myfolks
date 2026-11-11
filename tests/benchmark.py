"""Speed on made-up data: python3 tests/benchmark.py (needs a Python with cryptography).
Builds a temporary store of 5,000 cards and 20,000 details, then deletes it."""

import random
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))
from loader import load  # noqa: E402

load()
from myfolks import cards, commands, db, importer, wake  # noqa: E402
from myfolks.device_key import DeviceKeys  # noqa: E402
from myfolks.vault import Vault  # noqa: E402

FIRST = ["Ana", "Ben", "Chen", "Dara", "Eli", "Farah", "Gita", "Hugo", "Ines", "Jun", "Kira", "Liam", "Mina",
         "Noah", "Omar", "Pia", "Quan", "Rosa", "Seth", "Tara", "Uma", "Viktor", "Wen", "Xena", "Yara", "Zane"]
TOPICS = ["allergic to peanuts", "likes green tea", "works at a made up company", "birthday March 3",
          "lives in a made up town", "plays chess on Tuesdays", "prefers window seats", "owes me lunch"]


def show(label, samples, unit="ms", scale=1000):
    print(f"  {label:46s} median {statistics.median(samples) * scale:8.2f} {unit}   slowest {max(samples) * scale:8.2f} {unit}")


def timed(action, runs):
    samples = []
    for number in range(runs):
        started = time.perf_counter()
        action(number)
        samples.append(time.perf_counter() - started)
    return samples


def main():
    with tempfile.TemporaryDirectory() as folder:
        directory = Path(folder)
        vault = Vault(directory, keys=DeviceKeys(directory, use_keychain=False))
        vault.setup()
        with vault.write() as connection:
            change = db.Change(connection, "bench", "bench")
            for i in range(5000):
                card_id = cards.add_card(change, f"{FIRST[i % 26]} Person{i}", "bench")
                for j in range(4):
                    cards.add_detail(change, card_id, f"{TOPICS[(i + j) % 8]} note{j}", "bench")
            change.finish("bench")
        size = vault.store_path.stat().st_size / 1e6
        print(f"1. /contacts at 5,000 cards and 20,000 details ({size:.2f} MB file, 40 runs each)")
        ask = lambda *_args: None  # noqa: E731
        run = lambda text: commands.handle(text, platform="cli", vault=vault, ask=ask)  # noqa: E731
        show("lookup, exact name and words", timed(lambda i: run(f"ana person{(i * 26) % 5000} allergic"), 40))
        show("card view", timed(lambda i: run(f"ben person{(i * 26 + 1) % 5000}"), 40))
        show("near name (checks every name)", timed(lambda i: run(f"benn persn{(i * 26 + 1) % 5000} tea"), 40))
        show("save", timed(lambda i: run(f'save "Dara Person{(i * 26 + 3) % 5000}" extra note {i}'), 40))

        print("2. Chat hooks on each message (MyFolks's own check, 20,000 runs each)")
        settings = wake.Settings(lambda key, default=None: default)
        gate, note = wake.gateway_hook(settings), wake.llm_hook(settings)
        plain, woken = SimpleNamespace(text="hi there, how are you today?"), SimpleNamespace(text="Myfolks, mel dog")
        for label, action in [
            ("wake word hook, ordinary message", lambda _i: gate(event=plain)),
            ("wake word hook, wake word message", lambda _i: gate(event=woken)),
            ("AI note hook, ordinary message", lambda _i: note(user_message="hi there", platform="telegram")),
            ("AI note hook, message naming myfolks", lambda _i: note(user_message="I installed myfolks", platform="telegram")),
        ]:
            show(label, timed(action, 20000), unit="us", scale=1e6)

    with tempfile.TemporaryDirectory() as folder:
        directory = Path(folder)
        vault = Vault(directory, keys=DeviceKeys(directory, use_keychain=False))
        vault.setup()
        commands.handle("save Priya likes tea", platform="cli", vault=vault)
        rng = random.Random(7)
        word = lambda: "".join(rng.choice("bcdfghjklmnpqrstvwxz") + rng.choice("aeiou") for _ in range(4)).capitalize()  # noqa: E731
        contacts = [importer.Incoming(name=f"{word()} {word()}", phones=[f"+1 202 555 {i:04d}"]) for i in range(5000)]
        done, samples = threading.Event(), []
        worker = threading.Thread(target=lambda: (importer.import_in_batches(vault, contacts, "bench import"), done.set()))
        worker.start()
        while not done.is_set():
            started = time.perf_counter()
            commands.handle("priya tea", platform="cli", vault=vault)
            samples.append(time.perf_counter() - started)
        worker.join()
        print(f"3. Lookup while 5,000 contacts import ({len(samples)} lookups)")
        show("lookup during import", samples)


if __name__ == "__main__":
    main()
