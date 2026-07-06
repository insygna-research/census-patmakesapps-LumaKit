"""Persistent per-user Telegram personality settings."""

import json

from core.paths import get_data_dir


CONFIG_PATH = get_data_dir() / "telegram_user_config.json"

# Tool-access role for non-owner users; see core/approval_policy.py (S-6).
DEFAULT_ROLE = "trusted"
_KNOWN_ROLES = {"trusted", "limited"}


def _normalize_role(value) -> str:
    role = str(value or "").strip().lower()
    return role if role in _KNOWN_ROLES else DEFAULT_ROLE


def load_user_configs():
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}

    if not isinstance(data, dict):
        return {}

    result = {}
    for chat_id, config in data.items():
        if not isinstance(config, dict):
            continue
        result[str(chat_id)] = {
            "personality_prompt": str(config.get("personality_prompt", "") or "").strip(),
            "voice_replies": bool(config.get("voice_replies", False)),
            "voice_name": str(config.get("voice_name", "") or "").strip(),
            "role": _normalize_role(config.get("role")),
        }
    return result


def save_user_configs(configs):
    payload = {}
    for chat_id, config in configs.items():
        payload[str(chat_id)] = {
            "personality_prompt": str(config.get("personality_prompt", "") or "").strip(),
            "voice_replies": bool(config.get("voice_replies", False)),
            "voice_name": str(config.get("voice_name", "") or "").strip(),
            "role": _normalize_role(config.get("role")),
        }

    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def get_user_role(chat_id) -> str:
    """Role for a non-owner Telegram user (owner is resolved by core.auth)."""
    if chat_id is None:
        return DEFAULT_ROLE
    config = load_user_configs().get(str(chat_id))
    if not config:
        return DEFAULT_ROLE
    return _normalize_role(config.get("role"))


def set_user_role(chat_id, role) -> str:
    normalized = _normalize_role(role)
    configs = load_user_configs()
    entry = configs.get(str(chat_id)) or {
        "personality_prompt": "",
        "voice_replies": False,
        "voice_name": "",
    }
    entry["role"] = normalized
    configs[str(chat_id)] = entry
    save_user_configs(configs)
    return normalized
