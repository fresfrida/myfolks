"""`hermes myfolks ...` terminal commands."""

from __future__ import annotations

import getpass
import sys

from . import messages


def setup_parser(parser) -> None:
    commands = parser.add_subparsers(dest="myfolks_command", required=True)
    commands.add_parser("setup", help="Create the encrypted store and show the recovery code once")
    commands.add_parser("recover", help="Open the store on this device with the recovery code")
    commands.add_parser("pair", help="Make a one-time code to link your messaging account")
    importing = commands.add_parser("import", help="Import contacts from a vCard or CSV file")
    importing.add_argument("path", help="Path to a .vcf or .csv file")


def run(args) -> int:
    handlers = {"setup": cmd_setup, "recover": cmd_recover, "pair": cmd_pair, "import": cmd_import}
    return handlers[args.myfolks_command](args)


def cmd_setup(_args, *, vault=None, stdout=None) -> int:
    from .vault import AlreadySetUp, Vault

    out = stdout or sys.stdout
    if not out.isatty():
        print(messages.SETUP_NEEDS_TERMINAL, file=sys.stderr)
        return 1
    vault = vault or Vault()
    try:
        code = vault.setup()
    except AlreadySetUp:
        print(messages.SETUP_ALREADY, file=out)
        return 1
    print(messages.SETUP_DONE, file=out)
    print(messages.SETUP_CODE_INTRO, file=out)
    print(code, file=out)
    print(messages.SETUP_CODE_NEEDED, file=out)
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


def cmd_pair(_args, *, vault=None, stdout=None) -> int:
    from . import owner
    from .vault import NotSetUp, Refused, Vault

    out = stdout or sys.stdout
    vault = vault or Vault()
    try:
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


def cmd_import(args, *, vault=None, stdout=None) -> int:
    from pathlib import Path

    from . import importer
    from .vault import Busy, NotSetUp, Refused, Vault

    out = stdout or sys.stdout
    vault = vault or Vault()
    path = Path(args.path).expanduser()
    try:
        contacts = importer.parse_file(path)
    except (OSError, importer.ImportFailed):
        print(messages.IMPORT_FAILED, file=out)
        return 1
    try:
        with vault.write() as connection:
            summary = importer.apply_contacts(connection, contacts, f"{path.name} import")
    except NotSetUp:
        print(messages.NOT_SET_UP, file=out)
        return 1
    except Refused:
        print(messages.LOCKED, file=out)
        return 1
    except Busy:
        print(messages.BUSY, file=out)
        return 1
    print(messages.import_summary(summary.new, summary.merged, summary.review, summary.unchanged, summary.skipped, summary.trimmed), file=out)
    return 0
