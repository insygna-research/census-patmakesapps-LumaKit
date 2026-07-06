"""Deliver an image to the current user on whatever surface they're using."""

from __future__ import annotations

from tools.comms.delivery import deliver_image_to_current_user, resolve_image_path


def get_send_photo_tool():
    return {
        "name": "send_photo",
        "description": (
            "Send an existing image file to the user. Routing is automatic: in the "
            "web UI it appears inline in the chat; in Telegram it arrives as a photo. "
            "Use this whenever the user asks to see an image file or a saved screenshot."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the image file to send.",
                },
                "caption": {
                    "type": "string",
                    "description": "Optional caption to include with the image.",
                },
            },
            "required": ["path"],
        },
        "execute": _send_photo,
    }


def _send_photo(inputs):
    raw_path = inputs.get("path", "")
    if not raw_path:
        return {"error": "path is required"}

    path = resolve_image_path(raw_path)
    caption = inputs.get("caption", "")
    return deliver_image_to_current_user(path, caption=caption)
