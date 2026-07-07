"""§2 provider adapters with mocked transports."""

import json
from unittest import mock

import pytest

from core import providers
from core.providers.anthropic_provider import AnthropicClient
from core.providers.openai_compat import OpenAICompatClient
from ollama_client import OllamaClient

INTERNAL_MESSAGES = [
    {"role": "system", "content": "You are Lumi.", "created_at": "2026-01-01"},
    {"role": "user", "content": "read a file"},
    {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "read_file", "arguments": {"path": "a.txt"}}},
        {"function": {"name": "read_file", "arguments": {"path": "b.txt"}}},
    ]},
    {"role": "tool", "name": "read_file", "content": "contents A"},
    {"role": "tool", "name": "read_file", "content": "contents B"},
    {"role": "user", "content": "look", "images": ["iVBORw0KGgoAAAANSUhEUg=="]},
]


def test_factory_default_is_ollama(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", {"llm_provider": ""})
    assert isinstance(providers.create_llm_client(), OllamaClient)


def test_factory_provider_selection(monkeypatch):
    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", {"llm_provider": ""})
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(providers.create_llm_client(), AnthropicClient)
    monkeypatch.setenv("LLM_PROVIDER", "xai")
    client = providers.create_llm_client()
    assert isinstance(client, OpenAICompatClient)
    assert client.base_url == "https://api.x.ai/v1"
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    assert isinstance(providers.create_llm_client(), OllamaClient)


def _clean_model_env(monkeypatch):
    for var in ("LLM_MODEL", "LLM_FALLBACK_MODEL", "LLM_BASE_URL", "LLM_API_KEY",
                "OLLAMA_MODEL", "OLLAMA_FALLBACK_MODEL"):
        monkeypatch.delenv(var, raising=False)


def test_default_model_is_provider_aware(monkeypatch):
    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", {"llm_provider": ""})
    _clean_model_env(monkeypatch)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3")
    monkeypatch.setenv("OLLAMA_FALLBACK_MODEL", "gemma4")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    assert providers.default_model() == "qwen3"
    assert providers.default_fallback_model() == "gemma4"
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    # switching provider must not send an Ollama model name to a remote API
    assert providers.default_model() == "claude-opus-4-8"
    assert providers.default_fallback_model() == ""
    monkeypatch.setenv("LLM_MODEL", "my-explicit")
    assert providers.default_model() == "my-explicit"


def test_per_provider_model_choice_wins(monkeypatch):
    monkeypatch.setattr(
        "core.app_runtime_config.APP_RUNTIME_CONFIG",
        {
            "llm_provider": "anthropic",
            "provider_models": {"anthropic": "claude-sonnet-5", "openai": "gpt-5.2-mini"},
            "provider_fallback_models": {"anthropic": "claude-haiku-4-5-20251001"},
        },
    )
    _clean_model_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "env-model")  # user's UI choice beats env
    assert providers.default_model() == "claude-sonnet-5"
    assert providers.default_fallback_model() == "claude-haiku-4-5-20251001"
    # a choice saved for another provider applies when switching to it…
    assert providers.default_model("openai") == "gpt-5.2-mini"
    # …and providers without a choice fall back to env, then built-in default
    assert providers.default_model("xai") == "env-model"


def test_fingerprint_changes_when_model_choice_saved(monkeypatch):
    cfg = {"llm_provider": "anthropic", "provider_models": {}}
    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", cfg)
    _clean_model_env(monkeypatch)
    before = providers.provider_fingerprint()
    cfg["provider_models"] = {"anthropic": "claude-sonnet-5"}
    assert providers.provider_fingerprint() != before  # triggers hot-swap


def test_fingerprint_tracks_provider_config(monkeypatch):
    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", {"llm_provider": ""})
    _clean_model_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    fp_ollama = providers.provider_fingerprint()
    assert providers.provider_fingerprint() == fp_ollama  # stable while unchanged
    monkeypatch.setenv("LLM_PROVIDER", "xai")
    assert providers.provider_fingerprint() != fp_ollama


def test_task_runner_hot_swaps_client(monkeypatch):
    from core.task_runner import TaskRunner

    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", {"llm_provider": ""})
    _clean_model_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    runner = TaskRunner()
    first = runner._get_ollama()
    assert isinstance(first, OllamaClient)
    assert runner._get_ollama() is first  # cached while config unchanged
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert isinstance(runner._get_ollama(), AnthropicClient)


def test_agent_hot_swaps_client(monkeypatch):
    from agent import Agent

    monkeypatch.setattr("core.app_runtime_config.APP_RUNTIME_CONFIG", {"llm_provider": ""})
    _clean_model_env(monkeypatch)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    agent = Agent.__new__(Agent)
    agent._llm_fingerprint = None
    agent.ensure_current_llm_client()
    first = agent.ollama
    assert isinstance(first, OllamaClient)
    agent.ensure_current_llm_client()
    assert agent.ollama is first
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    agent.ensure_current_llm_client()
    assert isinstance(agent.ollama, AnthropicClient)
    assert agent.default_model == "claude-opus-4-8"


def test_openai_message_conversion():
    client = OpenAICompatClient("https://api.openai.com/v1", api_key="sk-test")
    converted = client._convert_messages(INTERNAL_MESSAGES)
    assert "created_at" not in converted[0]
    # positional tool-call id matching
    assert converted[2]["tool_calls"][0]["id"] == converted[3]["tool_call_id"]
    assert converted[2]["tool_calls"][1]["id"] == converted[4]["tool_call_id"]
    assert isinstance(converted[2]["tool_calls"][0]["function"]["arguments"], str)
    assert converted[5]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_response_conversion():
    result = OpenAICompatClient._convert_response({
        "model": "gpt-5.2",
        "choices": [{"message": {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "call_x", "type": "function",
                            "function": {"name": "web_search", "arguments": "{\"query\": \"hi\"}"}}],
        }}],
    })
    assert result["message"]["content"] == ""
    assert result["message"]["tool_calls"][0]["function"]["arguments"] == {"query": "hi"}


def test_openai_chat_round_trip():
    client = OpenAICompatClient("https://api.openai.com/v1", api_key="sk-test")
    with mock.patch("core.providers.openai_compat.requests.post") as post:
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {
            "model": "gpt-5.2",
            "choices": [{"message": {"role": "assistant", "content": "hello!"}}],
        }
        resp.raise_for_status.return_value = None
        post.return_value = resp
        out = client.chat("gpt-5.2", INTERNAL_MESSAGES)
        assert out["message"]["content"] == "hello!"
        assert client.last_model_used == "gpt-5.2"
        assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_fallback_on_timeout():
    import requests as _requests

    client = OpenAICompatClient(
        "https://api.openai.com/v1", api_key="k", fallback_model="gpt-fallback"
    )
    with mock.patch("core.providers.openai_compat.requests.post") as post:
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {
            "model": "fb",
            "choices": [{"message": {"role": "assistant", "content": "fb reply"}}],
        }
        ok.raise_for_status.return_value = None
        post.side_effect = [_requests.Timeout(), ok]
        out = client.chat("gpt-main", [{"role": "user", "content": "hi"}])
        assert out["message"]["content"] == "fb reply"
        assert client.last_model_used == "gpt-fallback"


def test_anthropic_message_conversion():
    ac = AnthropicClient(api_key="sk-ant-test")
    system, msgs = ac._convert_messages(INTERNAL_MESSAGES)
    assert system == "You are Lumi."
    assert msgs[0]["role"] == "user"
    tool_use = [b for b in msgs[1]["content"] if b["type"] == "tool_use"]
    results = [b for b in msgs[2]["content"] if b["type"] == "tool_result"]
    assert len(results) == 2  # parallel results grouped into ONE user message
    assert results[0]["tool_use_id"] == tool_use[0]["id"]
    assert results[1]["tool_use_id"] == tool_use[1]["id"]
    assert msgs[3]["content"][0]["type"] == "image"


def test_anthropic_tool_mapping():
    tools = AnthropicClient._convert_tools([{
        "type": "function",
        "function": {"name": "read_file", "description": "Read",
                     "parameters": {"type": "object", "properties": {}}},
    }])
    assert tools[0]["name"] == "read_file"
    assert "input_schema" in tools[0]


def test_anthropic_response_conversion():
    class Block:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    class Resp:
        content = [Block(type="text", text="On it. "),
                   Block(type="tool_use", id="toolu_1", name="read_file", input={"path": "a"})]
        stop_reason = "tool_use"
        model = "claude-opus-4-8"
        usage = Block(input_tokens=1, output_tokens=2)

    result = AnthropicClient._convert_response(Resp())
    assert result["message"]["content"] == "On it. "
    assert result["message"]["tool_calls"][0]["function"]["arguments"] == {"path": "a"}
