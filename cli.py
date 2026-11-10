"""`hermes myfolks ...` terminal commands."""

from __future__ import annotations

import getpass
import sys

from . import messages


def setup_parser(parser) -> None:
    commands = parser.add_subparsers(dest="myfolks_command", required=True)
    commands.add_parser("setup", help="Create the encrypted store and show the recovery code once")
    commands.add_parser("recover", help="Open the store on this device with the recovery code")


def run(args) -> int:
    handlers = {"setup": cmd_setup, "recover": cmd_recover}
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
