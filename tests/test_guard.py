import os
from pathlib import Path

import pytest


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    data = home / "plugin-data" / "myfolks"
    (data / "versions").mkdir(parents=True)
    for name in ("store.enc", "device.key", "versions/1.enc"):
        (data / name).write_text("x")
    history = home / ".hermes_history"
    history.write_text("x")
    other = tmp_path / "work" / "notes.txt"
    other.parent.mkdir()
    other.write_text("x")
    return {"home": home, "data": data, "history": history, "other": other, "tmp": tmp_path}


@pytest.fixture
def blocked(env, mod):
    guard = mod("guard")

    def check(tool, args, cwd=None):
        return guard.touches_protected(tool, args, (env["data"].resolve(), env["history"].resolve()), str(env["home"]), cwd=cwd or str(env["other"].parent))

    return check


def test_read_store_blocked(env, blocked):
    assert blocked("read_file", {"path": str(env["data"] / "store.enc")})


def test_read_version_blocked(env, blocked):
    assert blocked("read_file", {"path": str(env["data"] / "versions" / "1.enc")})


def test_read_device_key_blocked(env, blocked):
    assert blocked("read_file", {"path": str(env["data"] / "device.key")})


def test_read_history_blocked(env, blocked):
    assert blocked("read_file", {"path": str(env["history"])})


def test_terminal_cat_blocked(env, blocked):
    assert blocked("terminal", {"command": f"cat {env['data'] / 'store.enc'}"})


def test_terminal_copy_blocked(env, blocked):
    assert blocked("terminal", {"command": f"cp {env['data'] / 'device.key'} /tmp/x && cat /tmp/x"})


def test_terminal_history_blocked(env, blocked):
    assert blocked("terminal", {"command": "tail -5 .hermes_history"})


def test_symlink_to_store_blocked_by_real_path(env, blocked):
    link = env["tmp"] / "innocent.txt"
    os.symlink(env["data"] / "store.enc", link)
    assert blocked("read_file", {"path": str(link)})


def test_symlinked_folder_blocked_by_real_path(env, blocked):
    link = env["tmp"] / "folder"
    os.symlink(env["data"], link)
    assert blocked("terminal", {"command": f"cat '{link}/device.key'"})


def test_relative_path_with_workdir_blocked(env, blocked):
    assert blocked("terminal", {"command": "cat myfolks/store.enc", "workdir": str(env["home"] / "plugin-data")})


def test_relative_path_from_cwd_blocked(env, blocked):
    assert blocked("read_file", {"path": "store.enc"}, cwd=str(env["data"]))


def test_hermes_home_variable_blocked(env, blocked):
    assert blocked("terminal", {"command": "cat $HERMES_HOME/.hermes_history"})
    assert blocked("terminal", {"command": "cat ${HERMES_HOME}/plugin-data/myfolks/store.enc"})


def test_tilde_blocked(env, blocked, monkeypatch):
    monkeypatch.setenv("HOME", str(env["home"]))
    assert blocked("read_file", {"path": "~/plugin-data/myfolks/device.key"})


def test_parent_dotdot_blocked(env, blocked):
    assert blocked("read_file", {"path": str(env["data"] / "versions" / ".." / "store.enc")})


def test_search_in_data_folder_blocked(env, blocked):
    assert blocked("search_files", {"pattern": "x", "path": str(env["data"])})


def test_write_over_store_blocked(env, blocked):
    assert blocked("write_file", {"path": str(env["data"] / "store.enc"), "content": "x"})


def test_execute_code_literal_blocked(env, blocked):
    assert blocked("execute_code", {"code": f"print(open('{env['data'] / 'store.enc'}').read())"})


def test_nested_arguments_blocked(env, blocked):
    assert blocked("tool_call", {"calls": [{"name": "read_file", "arguments": {"path": str(env["data"] / "store.enc")}}]})


TERMINAL_ONLY = ["setup", "recover", "pair", "import /tmp/x.vcf", "backup /tmp/x", "restore /tmp/x", "export /tmp/x"]
FORMS = [
    "hermes -p demo myfolks {sub}",
    "hermes myfolks {sub}",
    "hermes myfolks \"{word}\"{rest}",
    "hermes myfolks '{word}'{rest}",
    "hermes \"myfolks\" {sub}",
    "hermes 'myfolks' \"{word}\"{rest}",
    "hermes my\"folks\" {sub}",
    "hermes \"myfolks {word}\"{rest}",
    "hermes myfolks \\{word}{rest}",
    "cd /tmp; hermes  myfolks   {sub}",
    "true && HERMES_HOME=/x /usr/local/bin/hermes myfolks {sub}",
    "hermes myfolks -v {sub}",
    "HERMES MYFOLKS {upper}",
]


@pytest.mark.parametrize("sub", TERMINAL_ONLY)
@pytest.mark.parametrize("form", FORMS)
def test_terminal_only_commands_blocked(env, blocked, sub, form):
    word, _, rest = sub.partition(" ")
    command = form.format(sub=sub, word=word, rest=(" " + rest) if rest else "", upper=sub.upper())
    assert blocked("terminal", {"command": command}), command


@pytest.mark.parametrize("command", ["hermes myfolks --help", "hermes plugins list", "echo myfolks is great", "hermes myfolks"])
def test_other_myfolks_commands_allowed(env, blocked, command):
    assert not blocked("terminal", {"command": command})


def test_unrelated_file_allowed(env, blocked):
    assert not blocked("read_file", {"path": str(env["other"])})
    assert not blocked("terminal", {"command": f"cat {env['other']} | grep -i store.enc && ls"})


def test_writing_about_the_store_is_allowed(env, blocked):
    assert not blocked("write_file", {"path": str(env["other"]), "content": "see plugin-data/myfolks/store.enc and .hermes_history"})


def test_known_limit_wildcard_route_is_not_blocked(env, blocked):
    assert not blocked("terminal", {"command": f"cat {env['home']}/plugin-dat*/my*/sto*"})


def test_known_limit_parent_folder_search_is_not_blocked(env, blocked):
    assert not blocked("search_files", {"pattern": "x", "path": str(env["home"])})


def test_guard_error_never_breaks_tools(mod, monkeypatch):
    guard = mod("guard")
    monkeypatch.setattr(guard, "protected_paths", lambda: 1 / 0)
    assert guard.pre_tool_call("read_file", {"path": "/x"}) is None


def test_no_boundary_claims_in_source():
    root = Path(__file__).parent.parent
    for path in [*root.glob("*.py"), *root.glob("data/*.json")]:
        text = path.read_text().lower()
        assert "boundary" not in text and "impossible to" not in text, path.name


def test_register_declares_what_manifest_says():
    import sys

    import yaml_free

    registered = yaml_free.registered()
    manifest = yaml_free.manifest(Path(__file__).parent.parent / "plugin.yaml")
    assert sorted(registered["hooks"]) == sorted(manifest["provides_hooks"])
    assert sorted(registered["tools"]) == sorted(manifest["provides_tools"])
    assert registered["commands"] == ["contacts", "myfolks"]
    assert registered["cli"] == ["myfolks"]
    assert sys.modules["myfolks"] is not None
