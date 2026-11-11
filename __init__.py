"""MyFolks for Hermes: exact, private contact recall through /contacts."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    # Imported once here so handlers never depend on this folder still being importable later:
    # a running gateway can keep a handler after the plugin's files are replaced or removed.
    from . import ai_tool, cli, commands, guard, owner, wake

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
    ctx.register_command(
        "myfolks",
        handle_contacts,
        description="Look up your contacts (same as /contacts)",
        args_hint="<query>",
    )
    settings = wake.Settings(ctx.get_config)

    async def answer_at_ingress(event, gateway, args: str) -> bool:
        """Answer /contacts, /myfolks and the wake word before Hermes's session, through the gateway's
        public adapter send. Returns False, changing nothing, when this message isn't ours to answer."""
        import asyncio

        source = getattr(event, "source", None)
        platform = getattr(getattr(source, "platform", None), "value", None)
        adapters = getattr(gateway, "adapters", None)
        adapter = adapters.get(source.platform) if isinstance(adapters, dict) and source is not None else None
        if adapter is None or not platform:
            return False
        shared = ctx.get_config(owner.SHARED_SETTING, [])
        if not await asyncio.to_thread(commands.answers_at_ingress, args, platform=platform, source=source, shared=shared):
            return False
        reply = await asyncio.to_thread(commands.handle, args, platform=platform, source=source, ask=None, shared=shared)
        try:
            await adapter.send(source.chat_id, reply)
        except Exception as exc:
            logger.error("MyFolks reply could not be sent: %s", type(exc).__name__)
        return True

    ctx.register_hook("pre_tool_call", guard_tool_call)
    ctx.register_hook("pre_gateway_dispatch", wake.gateway_hook(settings, answer_at_ingress))
    ctx.register_hook("pre_llm_call", wake.llm_hook(settings))
    ctx.register_cli_command(
        "myfolks",
        "Set up, recover and manage MyFolks",
        cli.setup_parser,
        cli.run,
    )
