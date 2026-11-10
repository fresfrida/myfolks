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
