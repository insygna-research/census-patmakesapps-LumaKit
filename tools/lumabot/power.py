"""Explicit, approval-gated Raspberry Pi power controls for LumaBot."""

from __future__ import annotations

import subprocess

from tools.lumabot.motion import SCHEDULER


POWER_DELAY_S = 15
SYSTEMD_RUN = "/usr/bin/systemd-run"
SYSTEMCTL = "/usr/bin/systemctl"
SUDO = "/usr/bin/sudo"


def _command(action: str) -> list[str]:
    if action not in {"reboot", "poweroff"}:
        raise ValueError("unsupported power action")
    return [
        SUDO,
        "-n",
        SYSTEMD_RUN,
        "--quiet",
        "--collect",
        f"--unit=lumabot-{action}",
        f"--on-active={POWER_DELAY_S}s",
        SYSTEMCTL,
        action,
    ]


def _schedule(action: str, inputs: dict) -> dict:
    reason = str(inputs.get("reason", "")).strip()
    if not reason:
        raise ValueError("reason must not be empty")
    if len(reason) > 500:
        raise ValueError("reason must be 500 characters or fewer")

    motor_stop = SCHEDULER.stop()
    result = subprocess.run(
        _command(action),
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "sudo command failed"
        return {"error": f"Could not schedule Raspberry Pi {action}: {error}"}
    return {
        "scheduled": True,
        "action": action,
        "delay_s": POWER_DELAY_S,
        "motors_stopped": not bool(motor_stop.get("error")),
        "message": f"Raspberry Pi {action} scheduled in {POWER_DELAY_S} seconds.",
        "response_guidance": "Immediately acknowledge the action in one short sentence.",
    }


def _tool(action: str) -> dict:
    label = "reboot" if action == "reboot" else "shut down and fully power off"
    return {
        "name": f"lumabot_{action}",
        "description": (
            f"{label.capitalize()} the entire physical Raspberry Pi running LumaBot. "
            "This is not a LumaKit process restart. Use only when the owner explicitly asks "
            f"to {label} the robot. The action always requires approval, first stops the "
            "motors, and is delayed briefly so you can acknowledge it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the owner requested this power action.",
                }
            },
            "required": ["reason"],
        },
        "execute": lambda inputs: _schedule(action, inputs),
    }


def get_lumabot_reboot_tool():
    return _tool("reboot")


def get_lumabot_poweroff_tool():
    return _tool("poweroff")
