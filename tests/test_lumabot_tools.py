"""LumaBot tools use structured schemas and the normal tool-result cycle."""

import time

import pytest

from tool_registry import ToolRegistry
from tools.lumabot import client
from tools.lumabot.motion import (
    SCHEDULER,
    get_lumabot_drive_tool,
    get_lumabot_sequence_tool,
    get_lumabot_stop_tool,
)
from tools.lumabot.status import get_lumabot_status_tool


@pytest.fixture()
def registry():
    result = ToolRegistry()
    for tool in (
        get_lumabot_drive_tool(),
        get_lumabot_sequence_tool(),
        get_lumabot_stop_tool(),
        get_lumabot_status_tool(),
    ):
        result.register(tool, group="lumabot")
    return result


def test_drive_schema_guides_llm_without_phrase_parsing(registry):
    tool = registry.get("lumabot_drive")
    direction = tool["inputSchema"]["properties"]["direction"]
    duration = tool["inputSchema"]["properties"]["duration_s"]
    assert direction["enum"] == ["forward", "backward", "left", "right"]
    assert duration["maximum"] == 30.0
    assert "structured" in tool["description"].lower()
    assert "renewed in the background" in tool["description"].lower()
    assert "playful" in tool["description"].lower()


@pytest.mark.parametrize(
    "inputs",
    [
        {"direction": "sideways"},
        {"direction": "forward", "duration_s": 31},
    ],
)
def test_invalid_motion_never_reaches_daemon(registry, monkeypatch, inputs):
    monkeypatch.setattr(client, "drive", lambda *args: pytest.fail("HTTP called"))
    result = registry.execute("lumabot_drive", inputs)
    assert not result["success"]


def test_offline_daemon_surfaces_as_tool_failure(registry, monkeypatch):
    monkeypatch.setattr(
        client,
        "drive",
        lambda *args: {"error": "LumaBot is offline — is the LumaBot daemon running?"},
    )
    result = registry.execute("lumabot_drive", {"direction": "forward"})
    assert not result["success"]
    assert "offline" in result["error"]


def test_drive_returns_immediately_with_requested_duration(registry, monkeypatch):
    calls = []
    monkeypatch.setattr(
        client,
        "drive",
        lambda direction, speed, duration: calls.append((direction, speed, duration))
        or {
                "accepted": True,
                "direction": direction,
                "speed": speed,
                "duration_s": duration,
                "watchdog_active": True,
                "obstacle_safety_active": False,
            },
    )
    monkeypatch.setattr(client, "stop", lambda: {"stopped": True})
    result = registry.execute(
        "lumabot_drive",
        {"direction": "left", "speed": 0.2, "duration_s": 7},
    )
    assert result["success"]
    assert result["data"]["scheduled"] is True
    assert result["data"]["direction"] == "left"
    assert result["data"]["requested_duration_s"] == 7
    assert "under 12 words" in result["data"]["response_guidance"]
    assert calls[0] == ("left", 0.2, 3.0)
    SCHEDULER.cancel()


def test_sequence_runs_each_step_once_and_in_order(registry, monkeypatch):
    calls = []
    monkeypatch.setattr(
        client,
        "drive",
        lambda direction, speed, duration: calls.append((direction, duration))
        or {"accepted": True, "direction": direction},
    )
    result = registry.execute(
        "lumabot_sequence",
        {
            "steps": [
                {"direction": "forward", "speed": 0.2, "duration_s": 0.1},
                {"direction": "left", "speed": 0.2, "duration_s": 0.1},
                {"direction": "backward", "speed": 0.2, "duration_s": 0.1},
            ]
        },
    )
    assert result["success"]
    assert result["data"]["entire_request_scheduled"] is True
    assert result["data"]["step_count"] == 3
    time.sleep(0.35)
    assert calls == [("forward", 0.1), ("left", 0.1), ("backward", 0.1)]
    SCHEDULER.cancel()


def test_stop_and_status_return_daemon_results(registry, monkeypatch):
    monkeypatch.setattr(client, "stop", lambda: {"stopped": True})
    monkeypatch.setattr(client, "get_status", lambda: {"battery_pct": 75.0})
    assert registry.execute("lumabot_stop", {})["data"]["stopped"] is True
    assert registry.execute("lumabot_status", {})["data"]["battery_pct"] == 75.0
    assert "park" in registry.get("lumabot_stop")["description"].lower()
    assert "human-friendly" in registry.get("lumabot_status")["description"]
