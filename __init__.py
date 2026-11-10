"""MyFolks for Hermes: exact, private contact recall through /contacts."""

from __future__ import annotations

PLUGIN_ID = "myfolks"
DATA_DIR_FRAGMENT = "plugin-data/myfolks"


def _strings_in(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings_in(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings_in(item)


def block_store_access(tool_name: str, args: dict, task_id: str = "", **_context):
    """Refuse tool calls whose arguments name the plugin's data folder."""
    for text in _strings_in(args):
        if DATA_DIR_FRAGMENT in text.lower():
            return {"action": "block", "message": "MyFolks blocked this: the contact store is not available to AI tools."}
    return None


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
    ctx.register_hook("pre_tool_call", block_store_access)
    ctx.register_cli_command(
        "myfolks",
        "Set up, recover and manage MyFolks",
        _setup_cli,
        _run_cli,
    )
