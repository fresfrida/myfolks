import base64
import logging

import pytest


class FakeKeyring:
    def __init__(self):
        self.items = {}

    def set_password(self, service, account, value):
        self.items[(service, account)] = value

    def get_password(self, service, account):
        return self.items.get((service, account))


def _make(tmp_path, mod, keyring):
    keys = mod("device_key").DeviceKeys(tmp_path, keyring_module=keyring)
    vault = mod("vault").Vault(tmp_path, keys=keys)
    vault.setup()
    mod("commands").handle("save Mel likes tea", platform="cli", vault=vault)
    return keys, vault


def _stale_file(keys):
    keys.file_path.write_text(base64.b64encode(b"x" * 32).decode() + "\n")


def test_stale_file_does_not_hide_good_keychain_key(tmp_path, mod):
    keys, vault = _make(tmp_path, mod, FakeKeyring())
    _stale_file(keys)
    assert "likes tea" in mod("commands").handle("mel tea", platform="cli", vault=vault)


def test_good_file_only(tmp_path, mod):
    keys = mod("device_key").DeviceKeys(tmp_path, use_keychain=False)
    vault = mod("vault").Vault(tmp_path, keys=keys)
    vault.setup()
    mod("commands").handle("save Mel likes tea", platform="cli", vault=vault)
    assert keys.file_path.exists()
    assert "likes tea" in mod("commands").handle("mel tea", platform="cli", vault=vault)


def test_good_file_with_stale_keychain(tmp_path, mod):
    keys = mod("device_key").DeviceKeys(tmp_path, use_keychain=False)
    vault = mod("vault").Vault(tmp_path, keys=keys)
    vault.setup()
    mod("commands").handle("save Mel likes tea", platform="cli", vault=vault)
    stale = FakeKeyring()
    stale.items[("MyFolks for Hermes", keys._account)] = base64.b64encode(b"y" * 32).decode()
    reopened = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, keyring_module=stale))
    assert "likes tea" in mod("commands").handle("mel tea", platform="cli", vault=reopened)


def test_good_keychain_only(tmp_path, mod):
    keys, vault = _make(tmp_path, mod, FakeKeyring())
    assert not keys.file_path.exists()
    assert "likes tea" in mod("commands").handle("mel tea", platform="cli", vault=vault)


def test_no_key_opens_it(tmp_path, mod):
    keys, vault = _make(tmp_path, mod, FakeKeyring())
    keys._keyring.items.clear()
    _stale_file(keys)
    assert mod("commands").handle("mel tea", platform="cli", vault=vault).startswith("MyFolks can't open its data.")


def test_no_key_material_in_logs(tmp_path, mod, caplog):
    keyring = FakeKeyring()
    keys, vault = _make(tmp_path, mod, keyring)
    _stale_file(keys)
    with caplog.at_level(logging.DEBUG):
        mod("commands").handle("mel tea", platform="cli", vault=vault)
        keyring.items.clear()
        mod("commands").handle("mel tea", platform="cli", vault=vault)
    stored = [base64.b64encode(b"x" * 32).decode()]
    assert not any(secret in record.getMessage() for record in caplog.records for secret in stored)
