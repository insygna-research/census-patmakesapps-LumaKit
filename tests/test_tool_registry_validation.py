"""S-8: schema validation + argument normalization in the tool registry."""

import pytest

from tool_registry import ToolRegistry


@pytest.fixture()
def registry():
    reg = ToolRegistry()
    reg.register({
        "name": "echo",
        "description": "Echo back inputs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "num_results": {"type": "number", "minimum": 1, "maximum": 10},
                "mode": {"type": "string", "enum": ["fast", "slow"]},
                "flags": {"type": "array", "items": {"type": "string"}},
                "enabled": {"type": "boolean"},
            },
            "required": ["path"],
        },
        "execute": lambda inputs: dict(inputs),
    })
    return reg


def test_missing_required(registry):
    result = registry.execute("echo", {})
    assert not result["success"]
    assert "Missing required input: path" in result["error"]


def test_wrong_type(registry):
    result = registry.execute("echo", {"path": 123})
    assert not result["success"]
    assert "expected string" in result["error"]


def test_numeric_string_coerced(registry):
    result = registry.execute("echo", {"path": "x", "num_results": "5"})
    assert result["success"]
    assert result["data"]["num_results"] == 5.0


def test_unparseable_number_rejected(registry):
    result = registry.execute("echo", {"path": "x", "num_results": "lots"})
    assert not result["success"]
    assert "num_results" in result["error"]


def test_bounds(registry):
    result = registry.execute("echo", {"path": "x", "num_results": 99})
    assert not result["success"]
    assert "<=" in result["error"]


def test_enum(registry):
    result = registry.execute("echo", {"path": "x", "mode": "sideways"})
    assert not result["success"]
    assert "must be one of" in result["error"]


def test_array_item_type(registry):
    result = registry.execute("echo", {"path": "x", "flags": ["a", 2]})
    assert not result["success"]
    assert "flags[1]" in result["error"]


def test_boolean_string_coerced(registry):
    result = registry.execute("echo", {"path": "x", "enabled": "true"})
    assert result["success"]
    assert result["data"]["enabled"] is True


def test_stringified_args_blob(registry):
    result = registry.execute("echo", '{"path": "x"}')
    assert result["success"]
    assert result["data"]["path"] == "x"


def test_garbage_args_blob(registry):
    result = registry.execute("echo", "not json")
    assert not result["success"]
    assert "JSON object" in result["error"]


def test_bool_not_accepted_as_number(registry):
    result = registry.execute("echo", {"path": "x", "num_results": True})
    assert not result["success"]
