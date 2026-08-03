"""Agent and no-LLM Remote modes remain isolated and deterministic."""

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
    agent.registry.register(
        {
            "name": "remember",
            "description": "Store a memory.",
            "inputSchema": {"type": "object", "properties": {}},
            "execute": lambda inputs: {"stored": True},
        },
        group="memory",
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
    assert chat_store.get_chat_lumabot_profile("chat-a") == "off"

    chat_store.set_chat_lumabot_profile("chat-a", "agent")
    assert chat_store.get_chat_lumabot_profile("chat-a") == "agent"
    assert chat_store.get_chat_lumabot_profile("chat-b") == "off"

    chat_store.set_chat_lumabot_profile("chat-a", "remote")
    assert chat_store.get_chat_lumabot_profile("chat-a") == "remote"

    chat_store.set_chat_lumabot_profile("chat-a", "off")
    assert chat_store.get_chat_lumabot_profile("chat-a") == "off"


def test_mode_exposes_lumabot_and_memory_tools_with_compact_prompt():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot")

    names = [tool["function"]["name"] for tool in agent.get_tools_for_llm()]
    assert names == ["lumabot_drive", "remember"]
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


def test_memory_tools_execute_in_lumabot_mode():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot")

    result = agent.execute_tool("remember", {})
    assert result["success"] is True


def test_turning_mode_off_restores_full_tool_catalog():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot")
    agent.set_runtime_profile(None)

    names = {tool["function"]["name"] for tool in agent.get_tools_for_llm()}
    assert names == {"lumabot_drive", "read_file", "remember"}
    assert agent.build_system_prompt() == "FULL LUMAKIT PROMPT"


def test_remote_profile_exposes_no_tools_even_if_agent_is_called():
    agent = _minimal_agent()
    agent.set_runtime_profile("lumabot_remote")

    assert agent.get_tools_for_llm() == []
    assert "No tools are available" in agent.build_system_prompt()
    result = agent.execute_tool("lumabot_drive", {})
    assert result["success"] is False
    assert "lumabot_remote mode" in result["error"]


def test_cli_toggle_uses_shared_conversation_mode(monkeypatch, capsys):
    from core import commands

    saved = []
    refreshed = []
    monkeypatch.setattr(commands, "get_chat_lumabot_profile", lambda chat_id: "off")
    monkeypatch.setattr(
        commands,
        "set_chat_lumabot_profile",
        lambda chat_id, profile: saved.append((chat_id, profile)),
    )
    monkeypatch.setattr(
        commands,
        "apply_user_runtime",
        lambda agent, session, user_id, surface=None: refreshed.append(surface),
    )

    commands.cmd_lumabot("remote", object(), {"chat_id": "cli-chat"})
    assert saved == [("cli-chat", "remote")]
    assert refreshed == ["cli"]
    assert "structured commands bypass the LLM" in capsys.readouterr().out


def test_telegram_toggle_is_owner_only_and_uses_shared_mode(monkeypatch):
    from core import telegram_commands

    sent = []
    saved = []
    refreshed = []
    monkeypatch.setattr(telegram_commands, "OWNER_ID", "owner-chat")
    monkeypatch.setattr(
        telegram_commands,
        "send_message",
        lambda text, **kwargs: sent.append((text, kwargs)),
    )
    monkeypatch.setattr(
        telegram_commands,
        "get_chat_lumabot_profile",
        lambda chat_id: "off",
    )
    monkeypatch.setattr(
        telegram_commands,
        "set_chat_lumabot_profile",
        lambda chat_id, profile: saved.append((chat_id, profile)),
    )
    monkeypatch.setattr(
        telegram_commands,
        "apply_chat_runtime",
        lambda agent, session, chat_id: refreshed.append(chat_id),
    )

    session = {"chat_id": "shared-chat"}
    handled = telegram_commands.handle_telegram_command(
        "/lumabot remote", object(), session, "owner-chat", None
    )
    assert handled is True
    assert saved == [("shared-chat", "remote")]
    assert refreshed == ["owner-chat"]
    assert sent[-1][0].startswith("LumaBot Remote mode ON")
    assert "inline_keyboard" in sent[-1][1]["reply_markup"]

    telegram_commands.handle_telegram_command(
        "/lumabot remote", object(), session, "someone-else", None
    )
    assert sent[-1][0] == "This command is owner-only."


def test_remote_command_dispatches_once_without_llm(monkeypatch):
    from tools.lumabot import remote

    calls = []

    class Scheduler:
        def start(self, direction, speed, duration):
            calls.append(("start", direction, speed, duration))
            return {"accepted": True, "entire_request_scheduled": True}

        def start_continuous(self, direction, speed):
            calls.append(("continuous", direction, speed))
            return {"accepted": True, "continuous": True}

        def stop(self):
            calls.append(("stop",))
            return {"stopped": True}

    monkeypatch.setattr(remote, "SCHEDULER", Scheduler())
    latched = remote.execute_remote_command("drive forward")
    assert latched["ok"] is True
    assert calls == [("continuous", "forward", 0.3)]

    result = remote.execute_remote_command("drive forward 2 0.4")
    assert result["ok"] is True
    assert calls[-1] == ("start", "forward", 0.4, 2.0)

    reversed_result = remote.execute_remote_command("drive reverse")
    assert reversed_result["ok"] is True
    assert calls[-1] == ("continuous", "backward", 0.3)

    stopped = remote.execute_remote_command("park")
    assert stopped["ok"] is True
    assert calls[-1] == ("stop",)

    around = remote.execute_remote_action("turn_around", speed=0.5)
    assert around["ok"] is True
    assert calls[-1] == ("start", "left", 0.5, 2.0)


def test_remote_command_rejects_free_form_and_bad_bounds(monkeypatch):
    from tools.lumabot import remote

    monkeypatch.setattr(
        remote,
        "SCHEDULER",
        type("Scheduler", (), {"start": lambda *args: {}})(),
    )
    assert remote.execute_remote_command("come closer")["ok"] is False
    result = remote.execute_remote_command("drive forward 60")
    assert result["ok"] is False
    assert "between 0.1 and 30" in result["text"]


def test_telegram_button_uses_structured_callback_without_llm(monkeypatch):
    from core import telegram_commands

    calls = []
    monkeypatch.setattr(
        telegram_commands,
        "get_chat_lumabot_profile",
        lambda chat_id: "remote",
    )
    monkeypatch.setattr(
        telegram_commands,
        "execute_remote_action",
        lambda action, **kwargs: calls.append((action, kwargs))
        or {"ok": True, "text": "accepted"},
    )

    result = telegram_commands.handle_lumabot_callback(
        "lbot:drive:forward",
        {"chat_id": "robot-chat"},
    )
    assert result["ok"] is True
    assert calls == [("drive", {"direction": "forward", "continuous": True})]


def test_remote_number_validation_rejects_boolean():
    from tools.lumabot.remote import execute_remote_action

    try:
        execute_remote_action("drive", direction="forward", duration_s=True)
    except ValueError as error:
        assert "duration must be a number" in str(error)
    else:
        raise AssertionError("boolean duration should be rejected")
