"""Read-only LumaBot status tool."""

from tools.lumabot import client


def get_lumabot_status_tool():
    return {
        "name": "lumabot_status",
        "description": (
            "Read LumaBot's live distance, movement mode, motor outputs, motor readiness, "
            "battery percentage and voltage, camera availability, and daemon uptime. Use this "
            "for questions about battery life, distance, whether the robot is moving, or "
            "hardware readiness. After reading status, answer in concise, human-friendly "
            "language using only the fields relevant to the user's question; do not dump raw "
            "JSON. Clearly say when a requested reading is unavailable."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: client.get_status(),
    }
