import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from loader import load  # noqa: E402

load()


@pytest.fixture
def mod():
    def get(name):
        return importlib.import_module(f"myfolks.{name}")

    return get


@pytest.fixture
def vault(tmp_path, mod):
    instance = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    instance.recovery_code = instance.setup()
    return instance
