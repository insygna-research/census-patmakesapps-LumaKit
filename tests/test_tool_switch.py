"""Master tool-use switch (composer button / /tooluse) shared by every surface."""

from agent import Agent
from core import app_runtime_config
from tool_registry import ToolRegistry


def _minimal_agent():
    agent = Agent.__new__(Agent)
    agent.registry = ToolRegistry()
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
    agent._system_prompt_prefix = "Your tools: read_file\nFULL LUMAKIT PROMPT"
    agent._system_prompt_cache = {}
    agent._system_message_cache = {}
    agent._tools_schema_cache = {}
    agent._tools_schema_cache_version = None
    return agent


def _set_config(monkeypatch, **overrides):
    config = app_runtime_config.DEFAULT_CONFIG.copy()
    config.update(overrides)
    monkeypatch.setattr(app_runtime_config, "APP_RUNTIME_CONFIG", config)


def test_tools_are_on_by_default(monkeypatch):
    _set_config(monkeypatch)
    assert app_runtime_config.tools_enabled() is True

    agent = _minimal_agent()
    assert [t["function"]["name"] for t in agent.get_tools_for_llm()] == ["read_file"]
    assert "FULL LUMAKIT PROMPT" in agent.build_system_prompt()


def test_missing_key_in_an_older_config_file_still_means_on(monkeypatch):
    # Config files written before the switch existed have no tools_enabled key.
    monkeypatch.setattr(app_runtime_config, "APP_RUNTIME_CONFIG", {"safe_mode": True})
    assert app_runtime_config.tools_enabled() is True


def test_switch_off_sends_no_tools_and_swaps_the_prompt(monkeypatch):
    _set_config(monkeypatch, tools_enabled=False)
    agent = _minimal_agent()

    # No tool definitions at all — this is what a completion-only model needs.
    assert agent.get_tools_for_llm() == []

    prompt = agent.build_system_prompt()
    assert "FULL LUMAKIT PROMPT" not in prompt
    assert "Your tools: read_file" not in prompt
    assert "turned OFF" in prompt


def test_prompt_cache_does_not_survive_a_flip(monkeypatch):
    _set_config(monkeypatch, tools_enabled=True)
    agent = _minimal_agent()
    assert "FULL LUMAKIT PROMPT" in agent.build_system_prompt()

    _set_config(monkeypatch, tools_enabled=False)
    assert "FULL LUMAKIT PROMPT" not in agent.build_system_prompt()
    assert "turned OFF" in agent.build_system_message()["content"]


def test_round_trip_through_the_config_file(monkeypatch, tmp_path):
    monkeypatch.setattr(app_runtime_config, "CONFIG_PATH", tmp_path / "app_runtime_config.json")
    _set_config(monkeypatch)

    app_runtime_config.set_tools_enabled(False)
    assert app_runtime_config.tools_enabled() is False
    assert app_runtime_config.load_app_runtime_config()["tools_enabled"] is False

    app_runtime_config.set_tools_enabled(True)
    assert app_runtime_config.load_app_runtime_config()["tools_enabled"] is True
