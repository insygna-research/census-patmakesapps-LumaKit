"""Deliver a text message to the current user on whatever surface they're using."""

from __future__ import annotations

from tools.comms.delivery import deliver_text_to_current_user


def get_send_message_tool():
    return {
        "name": "send_message",
        "description": (
            "Push a standalone text message to the user. Routing is automatic: on "
            "Telegram it sends a Telegram message; in the web UI it appears in the "
            "chat feed. Only use this for out-of-band pings (e.g. progress from a "
            "background task) — your normal reply already reaches the user."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message text to send",
                },
            },
            "required": ["message"],
        },
        "execute": _send_message,
    }


def _send_message(inputs):
    message = str(inputs.get("message") or "").strip()
    if not message:
        return {"error": "message is required"}
    return deliver_text_to_current_user(message)
