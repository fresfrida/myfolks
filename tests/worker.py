"""Subprocess helper for the kill and two-writer tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from loader import load  # noqa: E402

load()
from myfolks.device_key import DeviceKeys  # noqa: E402
from myfolks.vault import Vault  # noqa: E402

mode, directory, label, count = sys.argv[1], Path(sys.argv[2]), sys.argv[3], int(sys.argv[4])
vault = Vault(directory, keys=DeviceKeys(directory, use_keychain=False), lock_timeout=60.0)
if mode == "append":
    for number in range(count):
        with vault.write() as connection:
            connection.execute("INSERT INTO settings(key,value) VALUES(?,?)", (f"{label}-{number}", "x"))
elif mode == "spin":
    number = 0
    while True:
        with vault.write() as connection:
            connection.execute(
                "INSERT INTO settings(key,value) VALUES('counter',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(number),),
            )
        print(number, flush=True)
        number += 1
