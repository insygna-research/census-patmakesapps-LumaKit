"""D-8: one tool error contract — failures always surface as success=false."""

import pytest

from tool_registry import ToolRegistry


@pytest.fixture()
def registry():
    reg = ToolRegistry()

    def make(name, fn):
        reg.register({
            "name": name,
            "description": name,
            "inputSchema": {"type": "object", "properties": {}},
            "execute": fn,
        })

    make("raises", lambda i: (_ for _ in ()).throw(RuntimeError("kaboom")))
    make("error_dict", lambda i: {"error": "SERPAPI_KEY environment variable not set", "query": "x"})
    make("success_false", lambda i: {"error": "timed out", "success": False})
    make("plain", lambda i: {"content": "hi"})
    make("success_with_error_field", lambda i: {"success": True, "error": "", "content": "ok"})
    return reg


def test_raising_tool_fails(registry):
    result = registry.execute("raises", {})
    assert result["success"] is False
    assert "kaboom" in result["error"]


def test_bare_error_dict_fails(registry):
    result = registry.execute("error_dict", {})
    assert result["success"] is False
    assert "SERPAPI_KEY" in result["error"]
    assert result["data"]["query"] == "x"  # original payload preserved


def test_success_false_dict_fails(registry):
    result = registry.execute("success_false", {})
    assert result["success"] is False
    assert "timed out" in result["error"]


def test_plain_result_succeeds(registry):
    result = registry.execute("plain", {})
    assert result["success"] is True
    assert result["data"]["content"] == "hi"


def test_explicit_success_with_empty_error_succeeds(registry):
    result = registry.execute("success_with_error_field", {})
    assert result["success"] is True
