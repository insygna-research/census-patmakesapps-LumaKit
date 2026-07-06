"""Capture a screenshot of the desktop and deliver it to the current user."""

from __future__ import annotations

from tools.comms.delivery import capture_screenshot_to_disk, deliver_image_to_current_user


def get_screenshot_tool():
    return {
        "name": "screenshot",
        "description": (
            "Take a screenshot of the current screen and deliver it to the user. "
            "Routing is automatic: inline in the web chat, or as a Telegram photo. "
            "Do NOT use this to send an existing image file — use send_photo for that."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "caption": {
                    "type": "string",
                    "description": "Optional caption to include with the screenshot.",
                },
            },
            "required": [],
        },
        "execute": _screenshot,
    }


def _screenshot(inputs):
    caption = inputs.get("caption", "")
    path = capture_screenshot_to_disk()
    result = deliver_image_to_current_user(path, caption=caption)
    if result.get("sent"):
        result["captured_path"] = str(path)
    return result
