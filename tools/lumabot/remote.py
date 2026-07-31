"""Deterministic LumaBot remote control; no language model involved."""

from __future__ import annotations

import shlex

from tools.lumabot import client
from tools.lumabot.motion import SCHEDULER


TURN_AROUND_FULL_SPEED_S = 1.0

REMOTE_HELP = (
    "LumaBot Remote commands\n\n"
    "/lumabot drive forward 1 0.3\n"
    "/lumabot drive backward 1 0.3\n"
    "/lumabot turn left 1 0.3\n"
    "/lumabot turn right 1 0.3\n"
    "/lumabot turn around\n"
    "/lumabot stop\n"
    "/lumabot park\n"
    "/lumabot status\n"
    "/lumabot agent\n"
    "/lumabot off\n\n"
    "Numbers are duration in seconds and speed from 0.1 to 1.0."
)


def _number(value, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number") from error


def _motion_values(duration_s=1.0, speed=0.3) -> tuple[float, float]:
    duration = _number(duration_s, "duration")
    throttle = _number(speed, "speed")
    if not 0.1 <= duration <= 30.0:
        raise ValueError("duration must be between 0.1 and 30 seconds")
    if not 0.1 <= throttle <= 1.0:
        raise ValueError("speed must be between 0.1 and 1.0")
    return duration, throttle


def _status_text(status: dict) -> str:
    if status.get("error"):
        return status["error"]
    battery = status.get("battery_pct")
    battery_text = f", battery {battery:.0f}%" if isinstance(battery, (int, float)) else ""
    return (
        f"LumaBot is {status.get('mode', 'unknown')}{battery_text}. "
        f"Motors {'ready' if status.get('motors_ready') else 'not ready'}."
    )


def execute_remote_action(
    action: str,
    *,
    direction: str | None = None,
    duration_s=1.0,
    speed=0.3,
) -> dict:
    """Execute one explicit remote action through the watchdog-safe scheduler."""
    action = str(action or "").lower()
    if action == "status":
        data = client.get_status()
        return {"ok": not bool(data.get("error")), "text": _status_text(data), "data": data}

    if action in {"stop", "park"}:
        data = SCHEDULER.stop()
        if data.get("error"):
            return {"ok": False, "text": data["error"], "data": data}
        text = "Parked. Motors released." if action == "park" else "Stopped."
        return {"ok": True, "text": text, "data": data}

    duration, throttle = _motion_values(duration_s, speed)
    if action == "turn_around":
        direction = "left"
        duration = min(5.0, TURN_AROUND_FULL_SPEED_S / throttle)
    elif action == "turn":
        if direction not in {"left", "right"}:
            raise ValueError("turn direction must be left or right")
    elif action == "drive":
        if direction not in {"forward", "backward"}:
            raise ValueError("drive direction must be forward or backward")
    else:
        raise ValueError("unknown LumaBot remote action")

    data = SCHEDULER.start(direction, throttle, duration)
    if data.get("error"):
        return {"ok": False, "text": data["error"], "data": data}
    label = "Turning around." if action == "turn_around" else f"Moving {direction}."
    return {"ok": True, "text": label, "data": data}


def execute_remote_command(arguments: str) -> dict:
    """Parse the documented slash-command grammar, never natural language."""
    try:
        parts = shlex.split(arguments)
    except ValueError as error:
        return {"ok": False, "text": f"{error}\n\n{REMOTE_HELP}"}
    if not parts or parts[0].lower() == "help":
        return {"ok": True, "text": REMOTE_HELP}

    command = parts[0].lower()
    try:
        if command in {"status", "stop", "park"} and len(parts) == 1:
            return execute_remote_action(command)
        if command == "drive" and 2 <= len(parts) <= 4:
            return execute_remote_action(
                "drive",
                direction=parts[1].lower(),
                duration_s=parts[2] if len(parts) >= 3 else 1.0,
                speed=parts[3] if len(parts) == 4 else 0.3,
            )
        if command == "turn" and 2 <= len(parts) <= 4:
            target = parts[1].lower()
            if target == "around" and len(parts) == 2:
                return execute_remote_action("turn_around")
            return execute_remote_action(
                "turn",
                direction=target,
                duration_s=parts[2] if len(parts) >= 3 else 1.0,
                speed=parts[3] if len(parts) == 4 else 0.3,
            )
    except ValueError as error:
        return {"ok": False, "text": f"{error}\n\n{REMOTE_HELP}"}
    return {"ok": False, "text": REMOTE_HELP}
