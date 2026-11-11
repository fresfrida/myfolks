"""Runs one myfolks terminal command against a test store, for the pseudo-terminal tests."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from loader import load  # noqa: E402

load()
from myfolks import cli  # noqa: E402
from myfolks.device_key import DeviceKeys  # noqa: E402
from myfolks.vault import Vault  # noqa: E402

directory, command = Path(sys.argv[1]), sys.argv[2]
vault = Vault(directory, keys=DeviceKeys(directory, use_keychain=False))
handler = getattr(cli, f"cmd_{command}")
target = sys.argv[3] if len(sys.argv) > 3 else None
sys.exit(handler(argparse.Namespace(path=target, output=target), vault=vault))
