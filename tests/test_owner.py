from types import SimpleNamespace

import pytest

REFUSED = "MyFolks isn't available here."


def sender(user_id="111", chat_type="dm", is_bot=False):
    return SimpleNamespace(user_id=user_id, chat_type=chat_type, is_bot=is_bot)


@pytest.fixture
def allow(mod, monkeypatch):
    owner = mod("owner")

    def set_users(*users, open_to_all=False):
        monkeypatch.setattr(owner, "allowed_users", lambda platform: (set(users), open_to_all))

    return set_users


@pytest.fixture
def send(vault, mod):
    commands = mod("commands")

    def go(text, source, platform="telegram", shared=None):
        return commands.handle(text, platform=platform, source=source, ask=None, vault=vault, shared=shared)

    return go


@pytest.fixture
def seeded(vault, mod):
    mod("commands").handle("save Priya likes tea", platform="cli", vault=vault)
    return vault


def code_from_cli(vault, mod):
    import io

    out = io.StringIO()
    assert mod("cli").cmd_pair(None, vault=vault, stdout=out) == 0
    return out.getvalue().strip().splitlines()[-1].split()[-1]


def test_sole_allowed_user_is_owner(seeded, allow, send):
    allow("111")
    assert "likes tea" in send("priya", sender())


def test_source_label_is_platform(seeded, allow, send):
    allow("111")
    send("save Priya likes cake", sender())
    assert "from Telegram" in send("priya cake", sender())


def test_other_user_refused_when_one_allowed(seeded, allow, send):
    allow("111")
    assert send("priya", sender("222")) == REFUSED


def test_group_refused_even_for_owner(seeded, allow, send):
    allow("111")
    assert send("priya", sender(chat_type="group")) == REFUSED


@pytest.mark.parametrize("chat_type", ["channel", "thread", "", None])
def test_other_chat_types_refused(seeded, allow, send, chat_type):
    allow("111")
    assert send("priya", sender(chat_type=chat_type)) == REFUSED


@pytest.mark.parametrize("user_id", [None, ""])
def test_missing_sender_refused(seeded, allow, send, user_id):
    allow("111")
    assert send("priya", sender(user_id=user_id)) == REFUSED


def test_missing_source_refused(seeded, allow, send):
    allow("111")
    assert send("priya", None) == REFUSED


def test_bot_author_refused(seeded, allow, send):
    allow("111")
    assert send("priya", sender(is_bot=True)) == REFUSED


def test_several_allowed_means_nobody_until_paired(seeded, allow, send):
    allow("111", "222")
    assert send("priya", sender("111")) == REFUSED


def test_open_to_all_is_not_an_owner(seeded, allow, send):
    allow("111", open_to_all=True)
    assert send("priya", sender("111")) == REFUSED


def test_no_allowlist_is_nobody(seeded, allow, send):
    allow()
    assert send("priya", sender("111")) == REFUSED


def test_pairing_links_owner_once(seeded, allow, send, mod):
    allow("111", "222")
    code = code_from_cli(seeded, mod)
    assert send(f"pair {code}", sender("222")) == "Linked. This chat is now yours."
    assert "likes tea" in send("priya", sender("222"))
    assert send("priya", sender("111")) == REFUSED
    assert send(f"pair {code}", sender("111")) == REFUSED


def test_pairing_refused_in_group(seeded, allow, send, mod):
    allow("111", "222")
    code = code_from_cli(seeded, mod)
    assert send(f"pair {code}", sender("222", chat_type="group")) == REFUSED
    assert send(f"pair {code}", sender("222")) == "Linked. This chat is now yours."


def test_wrong_codes_burn_the_code(seeded, allow, send, mod):
    allow("111", "222")
    code = code_from_cli(seeded, mod)
    for _attempt in range(5):
        assert send("pair WRONGCOD", sender("222")) == REFUSED
    assert send(f"pair {code}", sender("222")) == REFUSED


def test_expired_code_refused(seeded, mod):
    owner = mod("owner")
    with seeded.write() as connection:
        code = owner.new_pairing_code(connection, clock=lambda: 1000.0)
    with seeded.write() as connection:
        assert owner.try_pair(connection, "telegram", "222", code, clock=lambda: 1000.0 + 601) is False


def test_code_is_not_stored_in_clear(seeded, mod):
    code = code_from_cli(seeded, mod)
    with seeded.read() as connection:
        assert code not in str([tuple(row) for row in connection.execute("SELECT * FROM settings")])


def test_refusal_is_identical_before_setup(tmp_path, mod, allow):
    fresh = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    allow("111", "222")
    assert mod("commands").handle("priya", platform="telegram", source=sender("333"), vault=fresh) == REFUSED
    assert mod("commands").handle("pair ABCDEFGH", platform="telegram", source=sender("333"), vault=fresh) == REFUSED


def test_sole_owner_before_setup_is_told_to_set_up(tmp_path, mod, allow):
    fresh = mod("vault").Vault(tmp_path, keys=mod("device_key").DeviceKeys(tmp_path, use_keychain=False))
    allow("111")
    assert "hermes myfolks setup" in mod("commands").handle("priya", platform="telegram", source=sender("111"), vault=fresh)


@pytest.mark.parametrize("platform,label", [("cli", "terminal"), ("tui", "terminal"), ("local", "terminal"), ("desktop", "Desktop")])
def test_local_surfaces_are_owner(mod, platform, label):
    assert mod("owner").local_surface(platform) == label


@pytest.mark.parametrize("platform", ["telegram", "discord", "api_server", "webhook", "", None])
def test_other_surfaces_are_not_local(mod, platform):
    assert mod("owner").local_surface(platform) is None


def test_allowed_users_fails_closed_without_hermes(mod):
    assert mod("owner").allowed_users("telegram") == (set(), False)


def test_no_sender_ids_in_logs(seeded, allow, send, caplog):
    allow("987654321")
    with caplog.at_level("DEBUG"):
        send("priya", sender("987654321"))
        send("priya", sender("555555555"))
    assert "987654321" not in caplog.text and "555555555" not in caplog.text and "likes tea" not in caplog.text


READ_ONLY = ["telegram:222:read"]
CAN_ADD = ["telegram:222:add"]


def test_shared_read_can_look_up(seeded, allow, send):
    allow("111")
    assert "likes tea" in send("priya tea", sender("222"), shared=READ_ONLY)


@pytest.mark.parametrize("command", ["save Priya likes cake", "link Priya dog Biscuit", "correct Priya 1 likes cake", "undo", "review", "history Priya", "sav Priya likes cake"])
def test_shared_read_cannot_change_or_see_history(seeded, allow, send, command):
    allow("111")
    before = seeded.store_path.read_bytes()
    assert send(command, sender("222"), shared=READ_ONLY) == REFUSED
    assert seeded.store_path.read_bytes() == before


def test_shared_add_can_save(seeded, allow, send):
    allow("111")
    assert send("save Priya likes cake", sender("222"), shared=CAN_ADD) == "Saved to Priya."
    assert "likes cake" in send("priya cake", sender("222"), shared=CAN_ADD)


@pytest.mark.parametrize("command", ["link Priya dog Biscuit", "correct Priya 1 likes cake", "undo", "review merge 1"])
def test_shared_add_cannot_do_more(seeded, allow, send, command):
    allow("111")
    assert send(command, sender("222"), shared=CAN_ADD) == REFUSED


def test_removed_person_is_refused(seeded, allow, send):
    allow("111")
    assert "likes tea" in send("priya tea", sender("222"), shared=READ_ONLY)
    assert send("priya tea", sender("222"), shared=[]) == REFUSED


def test_shared_person_in_group_is_refused(seeded, allow, send):
    allow("111")
    assert send("priya tea", sender("222", chat_type="group"), shared=CAN_ADD) == REFUSED


def test_shared_entry_is_per_platform(seeded, allow, send):
    allow("111")
    assert send("priya tea", sender("222"), platform="discord", shared=READ_ONLY) == REFUSED


@pytest.mark.parametrize("entry", ["telegram:222", "telegram:222:admin", "222:read", "", "telegram::read"])
def test_malformed_entries_grant_nothing(seeded, allow, send, entry):
    allow("111")
    assert send("priya tea", sender("222"), shared=[entry]) == REFUSED


def test_default_is_empty(seeded, allow, send):
    allow("111")
    assert send("priya tea", sender("222")) == REFUSED


def test_owner_keeps_full_access_with_sharing_on(seeded, allow, send):
    allow("111")
    assert send("save Priya likes cake", sender("111"), shared=READ_ONLY) == "Saved to Priya."
