from types import SimpleNamespace

import io as _io

import pytest


class Terminal(_io.StringIO):
    def isatty(self):
        return True

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

    out = Terminal()
    assert mod("cli").cmd_pair(None, vault=vault, read_secret=lambda _p: vault.recovery_code, stdin=Terminal(), stdout=out, read_line=lambda _prompt: "REPLACE") == 0
    return out.getvalue().strip().splitlines()[-1].split()[-1]


def test_sole_allowed_user_is_owner(seeded, allow, send):
    allow("111")
    assert "likes tea" in send("priya", sender())


def test_source_label_is_platform(seeded, allow, send):
    allow("111")
    send("save Priya likes cake", sender())
    assert "· Telegram" in send("priya cake", sender())


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


def test_wrong_codes_lock_out_that_sender_only(seeded, allow, send, mod):
    allow("111", "222")
    code = code_from_cli(seeded, mod)
    for _attempt in range(5):
        assert send("pair WRONGCOD", sender("222")) == REFUSED
    assert send(f"pair {code}", sender("222")) == REFUSED
    assert send(f"pair {code}", sender("111")) == "Linked. This chat is now yours."


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


def test_shared_setting_accepts_comma_text(seeded, allow, send):
    allow("111")
    assert "likes tea" in send("priya tea", sender("222"), shared="telegram:333:add, telegram:222:read")
    assert send("save Priya x y", sender("222"), shared="telegram:333:add, telegram:222:read") == REFUSED


def test_owner_check_comes_before_any_name_question(seeded, allow, send):
    allow("111")
    assert send("prya tea", sender("222")) == REFUSED


def test_near_name_on_messaging_gives_question_and_command_only(seeded, allow, send):
    allow("111")
    reply = send("prya tea", sender("111"))
    assert reply.startswith("Did you mean Priya?") and "/contacts Priya tea" in reply and "likes tea" not in reply


def test_pair_refuses_without_a_terminal(seeded, mod, capsys):
    before = seeded.store_path.read_bytes()
    assert mod("cli").cmd_pair(None, vault=seeded, stdin=_io.StringIO(), stdout=Terminal()) == 1
    assert mod("cli").cmd_pair(None, vault=seeded, stdin=Terminal(), stdout=_io.StringIO()) == 1
    assert "Run this directly in your own terminal." in capsys.readouterr().err
    assert seeded.store_path.read_bytes() == before


def test_first_pair_needs_no_replace(seeded, mod):
    asked = []
    out = Terminal()
    assert mod("cli").cmd_pair(None, vault=seeded, read_secret=lambda _p: seeded.recovery_code, stdin=Terminal(), stdout=out, read_line=asked.append) == 0
    assert asked == []


def _link_owner(vault, mod, platform="telegram", user_id="111"):
    with vault.write() as connection:
        connection.execute("INSERT INTO owners(platform,user_id,created_at) VALUES(?,?,?)", (platform, user_id, "2026-01-01"))


def test_pair_shows_owner_and_needs_replace(seeded, mod):
    _link_owner(seeded, mod)
    prompts = []
    out = Terminal()
    assert mod("cli").cmd_pair(None, vault=seeded, read_secret=lambda _p: seeded.recovery_code, stdin=Terminal(), stdout=out, read_line=lambda p: prompts.append(p) or "no") == 1
    assert prompts == ["Already linked: telegram sender 111. A new code replaces that link on its platform once used. Type REPLACE to continue: "]
    assert out.getvalue().strip() == "Nothing was changed."
    with seeded.read() as connection:
        assert mod("db").get_setting(connection, "pairing_code") in (None, "")


def test_pair_replace_makes_a_code(seeded, mod):
    _link_owner(seeded, mod)
    out = Terminal()
    assert mod("cli").cmd_pair(None, vault=seeded, read_secret=lambda _p: seeded.recovery_code, stdin=Terminal(), stdout=out, read_line=lambda _p: "REPLACE") == 0
    assert "Send this in a private chat" in out.getvalue()


@pytest.mark.parametrize("access", ["read", "add"])
def test_shared_person_cannot_open_cards_by_number(seeded, allow, send, mod, access):
    allow("111")
    shared = [f"telegram:222:{access}"]
    for number in range(1, 6):
        assert send(f"#{number}", sender("222"), shared=shared) == "Nothing saved about that."
        assert send(f"#{number} tea", sender("222"), shared=shared) == "Nothing saved about that."
    assert send("#1", sender("111")).startswith("Priya")


def test_shared_person_ambiguity_lists_names_only(seeded, allow, send, mod):
    allow("111")
    with seeded.write() as connection:
        change = mod("db").Change(connection, "save", "terminal")
        mod("cards").add_card(change, "Priya", "terminal")
        change.finish("second Priya")
    reply = send("priya", sender("222"), shared=READ_ONLY)
    assert reply == "More than one contact has that name: Priya, Priya."
    assert "#" not in reply and "tea" not in reply
    assert "#1" in send("priya", sender("111"))
