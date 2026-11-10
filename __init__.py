"""MyFolks for Hermes: exact, private contact recall through /contacts."""

from __future__ import annotations


def register(ctx) -> None:
    # Imported once here so handlers never depend on this folder still being importable later:
    # a running gateway can keep a handler after the plugin's files are replaced or removed.
    from . import ai_tool, cli, commands, guard, owner

    def handle_contacts(raw_args: str, source=None, platform=None, **_context) -> str:
        shared = ctx.get_config(owner.SHARED_SETTING, [])
        return commands.handle(raw_args, platform=platform, source=source, ask=ctx.ask_choice, shared=shared)

    def guard_tool_call(tool_name: str, args: dict, task_id: str = "", **context):
        return guard.pre_tool_call(tool_name, args, task_id, **context)

    def tool_enabled() -> bool:
        return bool(ctx.get_config(ai_tool.SETTING, False))

    def run_tool(args: dict, **_context) -> str:
        return ai_tool.handle(args, enabled=tool_enabled(), tell_user=ctx.post_message)

    ctx.register_tool(ai_tool.TOOL_NAME, ai_tool.TOOLSET, ai_tool.SCHEMA, run_tool, check_fn=tool_enabled)
    ctx.register_command(
        "contacts",
        handle_contacts,
        description="Look up your contacts",
        args_hint="<query>",
    )
    ctx.register_hook("pre_tool_call", guard_tool_call)
    ctx.register_cli_command(
        "myfolks",
        "Set up, recover and manage MyFolks",
        cli.setup_parser,
        cli.run,
    )
