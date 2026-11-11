"""`hermes myfolks ...` terminal commands."""

from __future__ import annotations

import getpass
from typing import Optional
import sys

from . import messages


def setup_parser(parser) -> None:
    commands = parser.add_subparsers(dest="myfolks_command", required=True)
    commands.add_parser("setup", help="Create the encrypted store and show the recovery code once")
    commands.add_parser("recover", help="Open the store on this device with the recovery code")
    commands.add_parser("pair", help="Make a one-time code to link your messaging account")
    for name, text in (
        ("backup", "Write an encrypted backup, protected by a passphrase"),
        ("restore", "Load an encrypted backup"),
        ("export", "Write an unencrypted copy after a typed confirmation"),
    ):
        commands.add_parser(name, help=text).add_argument("path", help="File path")
    importing = commands.add_parser("import", help="Import contacts from a vCard or CSV file")
    importing.add_argument("path", help="Path to a .vcf or .csv file")


def run(args) -> int:
    handlers = {"setup": cmd_setup, "recover": cmd_recover, "pair": cmd_pair, "import": cmd_import, "backup": cmd_backup, "restore": cmd_restore, "export": cmd_export}
    return handlers[args.myfolks_command](args)


def create_store(vault) -> Optional[str]:
    """The one setup path, for hermes myfolks setup, the first /myfolks in the terminal and the
    Desktop page. Returns the recovery code, shown once, or None when the store already exists."""
    from .vault import AlreadySetUp

    try:
        return vault.setup()
    except AlreadySetUp:
        return None


def setup_lines(code: str) -> list[str]:
    return [messages.SETUP_DONE, messages.SETUP_CODE_INTRO, code, messages.SETUP_CODE_NEEDED]


def first_use_setup(vault) -> Optional[str]:
    """The first /contacts or /myfolks in Hermes's own terminal chat sets up a store that doesn't exist
    yet. Hermes wraps the terminal while chatting, so the caller checks the surface (the local terminal)
    instead of isatty; the reply goes only to that screen."""
    code = create_store(vault)
    return "\n".join(setup_lines(code)) if code else None


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
    """Write straight to the final path, private to this user. There is never a temporary copy."""
    import os

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def cmd_backup(args, *, vault=None, read_secret=None, stdin=None, stdout=None) -> int:
    from pathlib import Path

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
    path = Path(args.path).expanduser()
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
        _write_new_file(path, backup.seal(database, passphrase))
    except FileExistsError:
        print(messages.FILE_EXISTS, file=out)
        return 1
    print(messages.BACKUP_DONE, file=out)
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
        print(messages.SETUP_CODE_INTRO, file=out)
        print(code, file=out)
        print(messages.SETUP_CODE_NEEDED, file=out)
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
