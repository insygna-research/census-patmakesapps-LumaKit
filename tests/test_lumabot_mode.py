"""Focused LumaBot mode stays LLM-driven and scoped to one conversation."""

from agent import Agent
from tool_registry import ToolRegistry


def _minimal_agent():
    agent = Agent.__new__(Agent)
    agent.registry = ToolRegistry()
    agent.registry.register(
        {
            "name": "lumabot_drive",
            "description": "Drive the robot.",
            "inputSchema": {"type": "object", "properties": {}},
            "execute": lambda inputs: {"accepted": True},
        },
        group="lumabot",
    )
    agent.registry.register(
        {
            "name": "read_file",
            "description": "Read a file.",
            "inputSchema": {"type": "object", "properties": {}},
            "execute": lambda inputs: {"content": ""},
        },
        group="repo",
    )
    agent.runtime_profile = None
    agent._active_tool_groups = None
    agent._system_prompt_prefix = "FULL LUMAKIT PROMPT"
    agent._system_prompt_cache = {}
    agent._system_message_cache = {}
    agent._tools_schema_cache = {}
    agent._tools_schema_cache_version = None
    return agent


def test_mode_persists_per_conversation(tmp_path, monkeypatch):
    from core import chat_store

    monkeypatch.setattr(chat_store, "DB_PATH", tmp_path / "memory.db")
    assert chat_store.get_chat_lumabot_mode("chat-a") is False

    chat_store.set_chat_lumabot_mode("chat-a", True)
    assert chat_store.get_chat_lumabot_mode("chat-a") is True
    assert chat_store.get_chat_lumabot_mode("chat-b") is False

    chat_store.set_chat_lumabot_mode("chat-a", False)
    assert chat_store.get_chat_lumabot_mode("chat-a") is False


def test_mode_exposes_only_lumabot_tools_with_compact_prompt():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot")

    names = [tool["function"]["name"] for tool in agent.get_tools_for_llm()]
    assert names == ["lumabot_drive"]
    prompt = agent.build_system_prompt()
    assert "physical LumaBot" in prompt
    assert "natural-language intent yourself" in prompt
    assert "FULL LUMAKIT PROMPT" not in prompt


def test_mode_blocks_hidden_tool_execution():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot")

    result = agent.execute_tool("read_file", {})
    assert result["success"] is False
    assert "unavailable in lumabot mode" in result["error"]


def test_turning_mode_off_restores_full_tool_catalog():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot")
    agent.set_runtime_profile(None)

    names = {tool["function"]["name"] for tool in agent.get_tools_for_llm()}
    assert names == {"lumabot_drive", "read_file"}
    assert agent.build_system_prompt() == "FULL LUMAKIT PROMPT"


def test_cli_toggle_uses_shared_conversation_mode(monkeypatch, capsys):
    from core import commands

    saved = []
    refreshed = []
    monkeypatch.setattr(commands, "get_chat_lumabot_mode", lambda chat_id: False)
    monkeypatch.setattr(
        commands,
        "set_chat_lumabot_mode",
        lambda chat_id, enabled: saved.append((chat_id, enabled)),
    )
    monkeypatch.setattr(
        commands,
        "apply_user_runtime",
        lambda agent, session, user_id, surface=None: refreshed.append(surface),
    )

    commands.cmd_lumabot("on", object(), {"chat_id": "cli-chat"})
    assert saved == [("cli-chat", True)]
    assert refreshed == ["cli"]
    assert "LumaBot mode ON" in capsys.readouterr().out


def test_telegram_toggle_is_owner_only_and_uses_shared_mode(monkeypatch):
    from core import telegram_commands

    sent = []
    saved = []
    refreshed = []
    monkeypatch.setattr(telegram_commands, "OWNER_ID", "owner-chat")
    monkeypatch.setattr(telegram_commands, "send_message", sent.append)
    monkeypatch.setattr(telegram_commands, "get_chat_lumabot_mode", lambda chat_id: False)
    monkeypatch.setattr(
        telegram_commands,
        "set_chat_lumabot_mode",
        lambda chat_id, enabled: saved.append((chat_id, enabled)),
    )
    monkeypatch.setattr(
        telegram_commands,
        "apply_chat_runtime",
        lambda agent, session, chat_id: refreshed.append(chat_id),
    )

    session = {"chat_id": "shared-chat"}
    handled = telegram_commands.handle_telegram_command(
        "/lumabot on", object(), session, "owner-chat", None
    )
    assert handled is True
    assert saved == [("shared-chat", True)]
    assert refreshed == ["owner-chat"]
    assert sent[-1].startswith("LumaBot mode ON")

    telegram_commands.handle_telegram_command(
        "/lumabot on", object(), session, "someone-else", None
    )
    assert sent[-1] == "This command is owner-only."
