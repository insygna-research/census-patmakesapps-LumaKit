"""LLM-selectable LumaBot movement tools."""

from __future__ import annotations

import threading
import time

from tools.lumabot import client


WATCHDOG_LEASE_S = 3.0
RENEW_MARGIN_S = 0.25


class MotionScheduler:
    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_event: threading.Event | None = None

    def start(self, direction: str, speed: float, duration_s: float) -> dict:
        step = {"direction": direction, "speed": speed, "duration_s": duration_s}
        return self.start_sequence([step], single_drive=True)

    def start_sequence(self, steps: list[dict], single_drive: bool = False) -> dict:
        cancel_event = threading.Event()
        with self._lock:
            if self._cancel_event:
                self._cancel_event.set()
            self._cancel_event = cancel_event

        first = steps[0]
        started_at = time.monotonic()
        first_lease = min(WATCHDOG_LEASE_S, first["duration_s"])
        result = client.drive(first["direction"], first["speed"], first_lease)
        if result.get("error"):
            cancel_event.set()
            return result

        if len(steps) > 1 or first["duration_s"] > first_lease:
            worker = threading.Thread(
                target=self._run_sequence,
                args=(cancel_event, steps, started_at, first_lease),
                daemon=True,
                name="lumabot-motion-sequence",
            )
            worker.start()

        return {
            **result,
            "requested_duration_s": sum(step["duration_s"] for step in steps),
            "watchdog_lease_s": first_lease,
            "scheduled": True,
            "entire_request_scheduled": True,
            "step_count": len(steps),
            "steps": steps,
            "single_drive": single_drive,
            "response_guidance": (
                "Reply now with one playful sentence under 12 words. "
                "Do not list movement parameters or repeat any movement tool."
            ),
        }

    def _run_sequence(
        self,
        cancel_event: threading.Event,
        steps: list[dict],
        started_at: float,
        first_lease: float,
    ) -> None:
        first = steps[0]
        if not self._finish_step(
            cancel_event,
            first,
            started_at,
            first_lease,
        ):
            return

        for step in steps[1:]:
            if cancel_event.is_set():
                return
            step_started = time.monotonic()
            first_lease = min(WATCHDOG_LEASE_S, step["duration_s"])
            result = client.drive(step["direction"], step["speed"], first_lease)
            if result.get("error"):
                return
            if not self._finish_step(cancel_event, step, step_started, first_lease):
                return

    def _finish_step(
        self,
        cancel_event: threading.Event,
        step: dict,
        started_at: float,
        current_lease: float,
    ) -> bool:
        deadline = started_at + step["duration_s"]
        lease_deadline = started_at + current_lease
        while True:
            now = time.monotonic()
            remaining = deadline - now
            if remaining <= 0:
                return True
            if lease_deadline >= deadline:
                return not cancel_event.wait(remaining)

            renew_in = max(0.0, lease_deadline - now - RENEW_MARGIN_S)
            if cancel_event.wait(renew_in):
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            next_lease = min(WATCHDOG_LEASE_S, remaining)
            result = client.drive(step["direction"], step["speed"], next_lease)
            if result.get("error"):
                return False
            lease_deadline = time.monotonic() + next_lease

    def cancel(self) -> None:
        with self._lock:
            if self._cancel_event:
                self._cancel_event.set()
                self._cancel_event = None

    def stop(self) -> dict:
        self.cancel()
        return client.stop()


SCHEDULER = MotionScheduler()


def _drive(inputs: dict) -> dict:
    return SCHEDULER.start(
        inputs["direction"],
        inputs.get("speed", 0.3),
        inputs.get("duration_s", 1.0),
    )


def _sequence(inputs: dict) -> dict:
    raw_steps = inputs["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= 10:
        raise ValueError("steps must contain between 1 and 10 movement steps")

    steps = []
    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise ValueError(f"steps[{index}] must be an object")
        direction = raw.get("direction")
        if direction not in {"forward", "backward", "left", "right"}:
            raise ValueError(f"steps[{index}].direction is invalid")
        try:
            speed = float(raw.get("speed", 0.3))
            duration_s = float(raw.get("duration_s", 1.0))
        except (TypeError, ValueError) as error:
            raise ValueError(f"steps[{index}] speed and duration must be numbers") from error
        if not 0.1 <= speed <= 1.0:
            raise ValueError(f"steps[{index}].speed must be between 0.1 and 1.0")
        if not 0.1 <= duration_s <= 30.0:
            raise ValueError(f"steps[{index}].duration_s must be between 0.1 and 30")
        steps.append({"direction": direction, "speed": speed, "duration_s": duration_s})

    if sum(step["duration_s"] for step in steps) > 30.0:
        raise ValueError("total sequence duration must not exceed 30 seconds")
    return SCHEDULER.start_sequence(steps)


def get_lumabot_drive_tool():
    return {
        "name": "lumabot_drive",
        "description": (
            "Drive or rotate the physical LumaBot using structured direction, speed, and time. "
            "Use forward/backward for translation and left/right to spin in place. Positive "
            "direction is already calibrated to the robot; do not compensate for motor wiring. "
            "The duration is the user's total requested movement time. The tool returns as soon "
            "as movement is accepted, while short watchdog leases are renewed in the background "
            "until that total duration is reached. Use this tool exactly once for one continuous "
            "movement. For an ordered request containing then/after/multiple movements, use "
            "lumabot_sequence exactly once instead. A new drive replaces an active drive. Never "
            "repeat a movement after a result says entire_request_scheduled=true. The result "
            "states whether obstacle safety was active; do not claim it was active when false. "
            "After success, reply in one playful sentence under 12 words; do not mechanically "
            "recite direction, speed, or duration unless the user asks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["forward", "backward", "left", "right"],
                    "description": "Physical movement direction. Left/right rotate in place.",
                },
                "speed": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 1.0,
                    "description": "Normalized motor speed. Default 0.3; prefer low speeds indoors.",
                },
                "duration_s": {
                    "type": "number",
                    "minimum": 0.1,
                    "maximum": 30.0,
                    "description": "Total requested movement time in seconds. Default 1, maximum 30.",
                },
            },
            "required": ["direction"],
        },
        "execute": _drive,
    }


def get_lumabot_sequence_tool():
    return {
        "name": "lumabot_sequence",
        "description": (
            "Schedule one ordered physical LumaBot movement plan from a multi-step user request. "
            "Use this once when movements must happen in order, such as drive, then turn, then "
            "drive another direction. Each step fully runs before the next begins. The scheduler "
            "returns immediately, renews short watchdog leases in the background, and executes "
            "the supplied steps exactly once. Do not also call lumabot_drive for the same request "
            "and never repeat the sequence after entire_request_scheduled=true. Left/right spin "
            "in place; a 180-degree turn is approximate because the robot has no wheel encoders. "
            "After acceptance, reply in one playful sentence under 12 words rather than "
            "mechanically listing every step."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "Ordered movement steps; maximum 10 and 30 seconds total.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["forward", "backward", "left", "right"],
                            },
                            "speed": {"type": "number", "minimum": 0.1, "maximum": 1.0},
                            "duration_s": {"type": "number", "minimum": 0.1, "maximum": 30.0},
                        },
                        "required": ["direction"],
                    },
                }
            },
            "required": ["steps"],
        },
        "execute": _sequence,
    }


def get_lumabot_stop_tool():
    return {
        "name": "lumabot_stop",
        "description": (
            "Immediately stop LumaBot and release both motors. Use whenever the user asks the "
            "robot not to move, to stop now, to park, or to cancel current movement. Parking "
            "currently means stopping, cancelling scheduled motion, and coasting both motors. "
            "Confirm the stop briefly and naturally without reciting internal motor values."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: SCHEDULER.stop(),
    }
