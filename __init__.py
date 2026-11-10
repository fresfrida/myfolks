"""MyFolks for Hermes: exact, private contact recall through /contacts."""

from __future__ import annotations

def _setup_cli(parser) -> None:
    from . import cli

    cli.setup_parser(parser)


def _run_cli(args):
    from . import cli

    return cli.run(args)


def register(ctx) -> None:
    def handle_contacts(raw_args: str, source=None, platform=None, **_context) -> str:
        from . import commands

        return commands.handle(raw_args, platform=platform, source=source, ask=ctx.ask_choice)

    ctx.register_command(
        "contacts",
        handle_contacts,
        description="Look up your contacts",
        args_hint="<query>",
    )
    def guard_tool_call(tool_name: str, args: dict, task_id: str = "", **context):
        from . import guard

        return guard.pre_tool_call(tool_name, args, task_id, **context)

    ctx.register_hook("pre_tool_call", guard_tool_call)
    ctx.register_cli_command(
        "myfolks",
        "Set up, recover and manage MyFolks",
        _setup_cli,
        _run_cli,
    )
