"""`hermes myfolks ...` terminal commands."""

from __future__ import annotations

import getpass
from typing import Optional
import sys

from . import messages


def setup_parser(parser) -> None:
    commands = parser.add_subparsers(dest="myfolks_command", required=True)
    commands.add_parser("setup", help="Create the encrypted store and show the recovery code once")
    commands.add_parser("recover", help="Open the store on this computer with the recovery code")
    commands.add_parser("pair", help="Make a one-time code to link your messaging account")
    backing_up = commands.add_parser("backup", help="Write an encrypted backup of MyFolks, protected by a passphrase")
    backing_up.add_argument("-o", "--output", help=f"File or folder for the backup (default: ~/{BACKUP_PREFIX}<timestamp>{BACKUP_SUFFIX})")
    for name, text in (
        ("restore", "Load an encrypted backup"),
        ("export", "Write an unencrypted copy after a typed confirmation"),
    ):
        commands.add_parser(name, help=text).add_argument("path", help="File path")
    importing = commands.add_parser("import", help="Import contacts from a vCard or CSV file")
    importing.add_argument("path", help="Path to a .vcf or .csv file")
    syncing = commands.add_parser("sync", help="Bring in your Google contacts, read-only, with Hermes's Google sign-in")
    syncing.add_argument("state", nargs="?", choices=["off"], help="off: stop syncing")


def run(args) -> int:
    handlers = {"setup": cmd_setup, "recover": cmd_recover, "pair": cmd_pair, "import": cmd_import, "backup": cmd_backup, "restore": cmd_restore, "export": cmd_export, "sync": cmd_sync}
    return handlers[args.myfolks_command](args)


SETUP_AT, SETUP_FROM = "set_up_at", "set_up_from"
BACKUP_PREFIX, BACKUP_SUFFIX = "myfolks-backup-", ".mfbk"


def create_store(vault, surface: str = "terminal") -> Optional[str]:
    """The one setup path, for hermes myfolks setup and the Desktop page's setup screen. Never a chat.
    Records when and from where it ran. Returns the recovery code, shown once, or None if set up."""
    from . import db
    from .vault import AlreadySetUp

    try:
        code = vault.setup()
    except AlreadySetUp:
        return None
    with vault.write() as connection:
        db.set_setting(connection, SETUP_AT, db.now())
        db.set_setting(connection, SETUP_FROM, surface)
    return code


def recovery_code_lines(code: str) -> list[str]:
    """How a new recovery code is shown in the terminal: after setup, and after a restore into a new store."""
    return [messages.SETUP_CODE_INTRO, code, messages.SETUP_CODE_PURPOSE]


def setup_lines(code: str) -> list[str]:
    return [
        messages.SETUP_DONE,
        messages.SETUP_NEXT,
        messages.SETUP_STORED_HERE,
        "",
        *recovery_code_lines(code),
        "",
        messages.SETUP_BACKUP_INTRO,
        f"  {messages.SETUP_BACKUP_COMMAND}",
        messages.SETUP_BACKUP_RESULT,
        "",
        messages.SETUP_HERMES_BACKUP_HEADING,
        messages.SETUP_HERMES_BACKUP_NOTE,
    ]


def cmd_setup(_args, *, vault=None, stdout=None) -> int:
    from .vault import Vault

    out = stdout or sys.stdout
    if not out.isatty():
        print(messages.SETUP_NEEDS_TERMINAL, file=sys.stderr)
        return 1
    code = create_store(vault or Vault())
    if code is None:
        print(messages.SETUP_ALREADY, file=out)
        return 1
    for line in setup_lines(code):
        print(line, file=out)
    return 0


def cmd_recover(_args, *, vault=None, read_code=None, stdout=None) -> int:
    from .vault import NotSetUp, Refused, Vault

    out = stdout or sys.stdout
    vault = vault or Vault()
    code = (read_code or getpass.getpass)(messages.RECOVER_PROMPT)
    try:
        vault.recover(code)
    except NotSetUp:
        print(messages.NOT_SET_UP, file=out)
        return 1
    except Refused:
        print(messages.RECOVER_REFUSED, file=out)
        return 1
    print(messages.RECOVER_DONE, file=out)
    return 0


def cmd_pair(_args, *, vault=None, read_line=None, read_secret=None, stdin=None, stdout=None) -> int:
    from . import owner
    from .vault import NotSetUp, Refused, Vault

    out, source = stdout or sys.stdout, stdin or sys.stdin
    if not _in_terminal((source, out)):
        print(messages.TERMINAL_ONLY, file=sys.stderr)
        return 1
    vault = vault or Vault()
    if not _recovery_code_ok(vault, read_secret or getpass.getpass, out):
        return 1
    try:
        with vault.read() as connection:
            linked = owner.linked_owners(connection)
        if linked and (read_line or input)(messages.pair_ask_replace(linked)).strip() != "REPLACE":
            print(messages.CANCELLED, file=out)
            return 1
        with vault.write() as connection:
            code = owner.new_pairing_code(connection)
    except NotSetUp:
        print(messages.NOT_SET_UP, file=out)
        return 1
    except Refused:
        print(messages.LOCKED, file=out)
        return 1
    print(messages.PAIR_CODE_INTRO, file=out)
    print(messages.pair_instruction(code), file=out)
    return 0


def cmd_import(args, *, vault=None, stdin=None, stdout=None) -> int:
    from pathlib import Path

    from . import importer
    from .vault import Busy, NotSetUp, Refused, Vault

    out, source = stdout or sys.stdout, stdin or sys.stdin
    if not _in_terminal((source, out)):
        print(messages.TERMINAL_ONLY, file=sys.stderr)
        return 1
    vault = vault or Vault()
    path = Path(args.path).expanduser()
    try:
        contacts = importer.parse_file(path)
    except (OSError, importer.ImportFailed):
        print(messages.IMPORT_FAILED, file=out)
        return 1
    result = importer.import_in_batches(vault, contacts, f"{path.name} import")
    summary = result.summary
    if result.stopped is not None and result.applied == 0:
        print({NotSetUp: messages.NOT_SET_UP, Refused: messages.LOCKED, Busy: messages.BUSY}.get(type(result.stopped), messages.IMPORT_FAILED), file=out)
        return 1
    print(messages.import_summary(summary.new, summary.merged, summary.review, summary.unchanged, summary.skipped, summary.trimmed), file=out)
    if summary.aliases:
        print(messages.import_aliases(summary.aliases), file=out)
    if result.stopped is not None:
        print(messages.import_stopped(result.applied, result.total), file=out)
        return 1
    return 0


def _recovery_code_ok(vault, ask, out) -> bool:
    """Sensitive commands need the recovery code, typed privately, before they do anything.
    An AI driving a terminal never saw the code, so it can't pass this step."""
    from .vault import NotSetUp

    if not vault.exists():
        print(messages.NOT_SET_UP, file=out)
        return False
    try:
        ok = vault.check_recovery_code(ask(messages.RECOVER_PROMPT))
    except NotSetUp:
        print(messages.NOT_SET_UP, file=out)
        return False
    if not ok:
        print(messages.RECOVER_REFUSED, file=out)
    return ok


def _in_terminal(streams) -> bool:
    return all(stream.isatty() for stream in streams)


def _write_new_file(path, data: bytes) -> None:
    """Write straight to the final path, private to this user. There is never a temporary copy,
    and a write that fails part way removes what it made."""
    import os

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        os.unlink(path)
        raise


def backup_path(output: Optional[str], now=None):
    """Where hermes myfolks backup writes, following hermes backup: no -o means the home folder,
    a folder (or a path ending in a slash) gets the default name inside it, anything else is the file
    itself. Always absolute."""
    import os
    from datetime import datetime
    from pathlib import Path

    name = f"{BACKUP_PREFIX}{(now or datetime.now()).strftime('%Y-%m-%d-%H%M%S')}{BACKUP_SUFFIX}"
    if not output:
        return Path.home() / name
    path = Path(output).expanduser().resolve()
    return path / name if path.is_dir() or output.endswith((os.sep, "/")) else path


def cmd_backup(args, *, vault=None, read_secret=None, stdin=None, stdout=None) -> int:
    from . import backup
    from .vault import NotSetUp, Refused, Vault

    out, source = stdout or sys.stdout, stdin or sys.stdin
    if not _in_terminal((source, out)):
        print(messages.TERMINAL_ONLY, file=sys.stderr)
        return 1
    ask = read_secret or getpass.getpass
    vault = vault or Vault()
    if not _recovery_code_ok(vault, ask, out):
        return 1
    path = backup_path(args.output)
    if path.exists():
        print(messages.FILE_EXISTS, file=out)
        return 1
    passphrase = ask(messages.BACKUP_PROMPT)
    if len(passphrase) < backup.MIN_PASSPHRASE:
        print(messages.BACKUP_SHORT, file=out)
        return 1
    if ask(messages.BACKUP_PROMPT_AGAIN) != passphrase:
        print(messages.BACKUP_MISMATCH, file=out)
        return 1
    try:
        database = vault.database_bytes()
    except NotSetUp:
        print(messages.NOT_SET_UP, file=out)
        return 1
    except Refused:
        print(messages.LOCKED, file=out)
        return 1
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_new_file(path, backup.seal(database, passphrase))
    except FileExistsError:
        print(messages.FILE_EXISTS, file=out)
        return 1
    except OSError:
        print(messages.BACKUP_UNWRITABLE, file=out)
        return 1
    print(messages.backup_done(path), file=out)
    return 0


def cmd_restore(args, *, vault=None, read_secret=None, read_line=None, stdin=None, stdout=None) -> int:
    from pathlib import Path

    from . import backup
    from .vault import NotEmpty, Refused, Vault

    out, source = stdout or sys.stdout, stdin or sys.stdin
    if not _in_terminal((source, out)):
        print(messages.TERMINAL_ONLY, file=sys.stderr)
        return 1
    vault = vault or Vault()
    if vault.exists() and not _recovery_code_ok(vault, read_secret or getpass.getpass, out):
        return 1
    try:
        blob = Path(args.path).expanduser().read_bytes()
    except OSError:
        print(messages.RESTORE_REFUSED, file=out)
        return 1
    try:
        database = backup.unseal(blob, (read_secret or getpass.getpass)(messages.RESTORE_PROMPT))
    except backup.BackupRefused:
        print(messages.RESTORE_REFUSED, file=out)
        return 1
    try:
        try:
            code = vault.restore_database(database)
        except NotEmpty:
            if (read_line or input)(messages.RESTORE_ASK_REPLACE).strip() != "REPLACE":
                print(messages.RESTORE_CANCELLED, file=out)
                return 1
            code = vault.restore_database(database, replace=True)
    except Refused:
        print(messages.RESTORE_REFUSED, file=out)
        return 1
    print(messages.RESTORE_DONE, file=out)
    if code:
        for line in recovery_code_lines(code):
            print(line, file=out)
    return 0


def cmd_export(args, *, vault=None, read_line=None, read_secret=None, stdin=None, stdout=None) -> int:
    import json
    from pathlib import Path

    from . import backup
    from .vault import NotSetUp, Refused, Vault

    out, source = stdout or sys.stdout, stdin or sys.stdin
    if not _in_terminal((source, out)):
        print(messages.TERMINAL_ONLY, file=sys.stderr)
        return 1
    vault = vault or Vault()
    if not _recovery_code_ok(vault, read_secret or getpass.getpass, out):
        return 1
    path = Path(args.path).expanduser()
    if path.exists():
        print(messages.FILE_EXISTS, file=out)
        return 1
    if (read_line or input)(messages.EXPORT_ASK).strip() != "EXPORT":
        print(messages.RESTORE_CANCELLED, file=out)
        return 1
    try:
        with vault.read() as connection:
            document = backup.export_document(connection)
    except NotSetUp:
        print(messages.NOT_SET_UP, file=out)
        return 1
    except Refused:
        print(messages.LOCKED, file=out)
        return 1
    try:
        _write_new_file(path, json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8"))
    except FileExistsError:
        print(messages.FILE_EXISTS, file=out)
        return 1
    print(messages.EXPORT_DONE, file=out)
    return 0


_SYNC_FAILURES = frozenset({messages.SYNC_NO_SIGN_IN, messages.SYNC_NO_CONTACTS, messages.SYNC_UNREACHABLE, messages.NOT_SET_UP, messages.LOCKED, messages.BUSY, messages.ERROR})


def cmd_sync(args, *, vault=None, stdout=None) -> int:
    """hermes myfolks sync [off]: the same command as /myfolks sync, from the terminal."""
    from . import commands

    out = stdout or sys.stdout
    reply = commands.handle("sync off" if getattr(args, "state", None) == "off" else "sync", platform="cli", vault=vault)
    print(reply, file=out)
    return 1 if reply in _SYNC_FAILURES else 0
