"""Load the repo root as a package named `myfolks`, the way Hermes loads a directory plugin."""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    if "myfolks" in sys.modules:
        return sys.modules["myfolks"]
    spec = importlib.util.spec_from_file_location("myfolks", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["myfolks"] = module
    spec.loader.exec_module(module)
    return module


def save_hidden(vault, command):
    """Save a line, then hide it from chat the way the Desktop page does."""
    import importlib

    importlib.import_module("myfolks.commands").handle(f"save {command}", platform="cli", vault=vault)
    with vault.read() as connection:
        line_id = connection.execute("SELECT max(id) FROM details").fetchone()[0]
    importlib.import_module("myfolks.desktop_service").set_hidden(line_id, True, vault)
