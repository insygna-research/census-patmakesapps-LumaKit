"""LumaBot power tools schedule only fixed, delayed systemd actions."""

from subprocess import CompletedProcess

import pytest

from tool_registry import ToolRegistry
from tools.lumabot import power


@pytest.fixture()
def registry():
    result = ToolRegistry()
    result.register(power.get_lumabot_reboot_tool(), group="lumabot")
    result.register(power.get_lumabot_poweroff_tool(), group="lumabot")
    return result


@pytest.mark.parametrize("action", ["reboot", "poweroff"])
def test_power_tool_stops_motors_and_uses_fixed_command(registry, monkeypatch, action):
    stopped = []
    calls = []
    monkeypatch.setattr(power.SCHEDULER, "stop", lambda: stopped.append(True) or {"stopped": True})
    monkeypatch.setattr(
        power.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs))
        or CompletedProcess(command, 0, "", ""),
    )

    result = registry.execute(f"lumabot_{action}", {"reason": "owner requested"})

    assert result["success"] is True
    assert result["data"]["scheduled"] is True
    assert result["data"]["delay_s"] == 15
    assert stopped == [True]
    assert calls[0][0] == [
        "/usr/bin/sudo",
        "-n",
        "/usr/bin/systemd-run",
        "--quiet",
        "--collect",
        f"--unit=lumabot-{action}",
        "--on-active=15s",
        "/usr/bin/systemctl",
        action,
    ]
    assert calls[0][1] == {
        "capture_output": True,
        "text": True,
        "timeout": 5,
        "check": False,
    }


def test_reason_never_changes_the_command(registry, monkeypatch):
    calls = []
    monkeypatch.setattr(power.SCHEDULER, "stop", lambda: {"stopped": True})
    monkeypatch.setattr(
        power.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or CompletedProcess(command, 0, "", ""),
    )

    result = registry.execute("lumabot_poweroff", {"reason": "; arbitrary command"})

    assert result["success"] is True
    assert "; arbitrary command" not in calls[0]


def test_sudo_failure_is_a_tool_failure(registry, monkeypatch):
    monkeypatch.setattr(power.SCHEDULER, "stop", lambda: {"stopped": True})
    monkeypatch.setattr(
        power.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 1, "", "not allowed"),
    )

    result = registry.execute("lumabot_reboot", {"reason": "owner requested"})

    assert result["success"] is False
    assert "not allowed" in result["error"]


def test_empty_reason_is_rejected_before_stopping_motors(registry, monkeypatch):
    monkeypatch.setattr(
        power.SCHEDULER,
        "stop",
        lambda: pytest.fail("motors should not be touched for invalid input"),
    )
    result = registry.execute("lumabot_reboot", {"reason": "   "})
    assert result["success"] is False
