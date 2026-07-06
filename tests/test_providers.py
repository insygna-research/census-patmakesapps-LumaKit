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
