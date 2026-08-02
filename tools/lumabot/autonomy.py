"""Approval-gated autonomous driving for the physical LumaBot."""

from tools.lumabot import client


def get_lumabot_start_autonomy_tool():
    return {
        "name": "lumabot_start_autonomy",
        "description": (
            "Start LumaBot's local autonomous obstacle-avoidance mode. Use only when the owner "
            "explicitly asks the robot to roam or drive autonomously. This starts ongoing "
            "physical movement and always requires approval. The hardware daemon refuses to "
            "start unless motors, distance, motion, tilt, and battery safety checks pass. "
            "Use lumabot_stop to cancel autonomy immediately."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why the owner requested autonomous driving.",
                }
            },
            "required": ["reason"],
        },
        "execute": lambda inputs: client.start_autonomy(),
    }
