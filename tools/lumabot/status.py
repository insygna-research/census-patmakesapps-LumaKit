"""Read-only LumaBot status tool."""

from tools.lumabot import client


def get_lumabot_status_tool():
    return {
        "name": "lumabot_status",
        "description": (
            "Read LumaBot's live distance freshness, autonomous mode and controller state, "
            "motion/tilt/collision data, motor outputs and readiness, battery percentage and "
            "voltage, camera availability, and daemon uptime. Use this for questions about "
            "battery life, distance, autonomous driving, collisions, movement, or hardware "
            "readiness. After reading status, answer in concise, human-friendly "
            "language using only the fields relevant to the user's question; do not dump raw "
            "JSON. Clearly say when a requested reading is unavailable."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: client.get_status(),
    }
