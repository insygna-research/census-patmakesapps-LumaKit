"""Persistent app-owned runtime config for web/UI-managed overrides.

This layer sits above `.env` defaults but below per-surface/per-user overrides
such as the Telegram owner's `/model` settings.
"""

from __future__ import annotations

import json

from core.paths import get_data_dir


CONFIG_PATH = get_data_dir() / "app_runtime_config.json"

DEFAULT_CONFIG = {
    "primary_model": "",
    "fallback_model": "",
    "require_tool_approvals": True,
    # Master switch for tool calling. On by default — LumaKit is an agent.
    # Turning it off sends no tool definitions to the model at all, which is
    # what makes completion-only local models (dolphin3 and friends, which
    # reject any request carrying tools) usable for plain chat.
    "tools_enabled": True,
    # Safe mode keeps the always-confirm tool prompts and the workspace
    # filesystem sandbox. Owner can disable it (/safemode off) for full
    # machine access; the secrets denylist still applies.
    "safe_mode": True,
    # "" = follow the LLM_PROVIDER env var (default: ollama).
    "llm_provider": "",
    # Per-provider model choices from the Settings UI, e.g.
    # {"anthropic": "claude-sonnet-5"}. Switching providers restores the
    # user's model for that provider; empty = the provider's default.
    "provider_models": {},
    "provider_fallback_models": {},
}

_VALID_PROVIDERS = {"", "ollama", "anthropic", "openai", "xai"}


def _coerce_provider(value) -> str:
    provider = str(value or "").strip().lower()
    return provider if provider in _VALID_PROVIDERS else ""


def _coerce_provider_models(value) -> dict:
    if not isinstance(value, dict):
        return {}
    out = {}
    for key, model in value.items():
        provider = _coerce_provider(key)
        model = str(model or "").strip()
        if provider and model:
            out[provider] = model
    return out


def _coerce_bool(value, default=True):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def load_app_runtime_config():
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}

    config = DEFAULT_CONFIG.copy()
    if isinstance(data, dict):
        config.update(
            {
                "primary_model": str(data.get("primary_model", "") or "").strip(),
                "fallback_model": str(data.get("fallback_model", "") or "").strip(),
                "require_tool_approvals": _coerce_bool(
                    data.get("require_tool_approvals"),
                    True,
                ),
                "tools_enabled": _coerce_bool(data.get("tools_enabled"), True),
                "safe_mode": _coerce_bool(data.get("safe_mode"), True),
                "llm_provider": _coerce_provider(data.get("llm_provider")),
                "provider_models": _coerce_provider_models(data.get("provider_models")),
                "provider_fallback_models": _coerce_provider_models(
                    data.get("provider_fallback_models")
                ),
            }
        )
    return config


APP_RUNTIME_CONFIG = load_app_runtime_config()


def get_app_runtime_config():
    return APP_RUNTIME_CONFIG


def tools_enabled() -> bool:
    """Whether the model is allowed to call tools at all. On by default."""
    return _coerce_bool(APP_RUNTIME_CONFIG.get("tools_enabled"), True)


def set_tools_enabled(enabled: bool) -> bool:
    """Flip the master tool switch. Every surface shares this one setting."""
    config = APP_RUNTIME_CONFIG.copy()
    config["tools_enabled"] = bool(enabled)
    save_app_runtime_config(config)
    return tools_enabled()


def save_app_runtime_config(config):
    global APP_RUNTIME_CONFIG

    payload = DEFAULT_CONFIG.copy()
    payload.update(config)
    payload["primary_model"] = str(payload.get("primary_model", "") or "").strip()
    payload["fallback_model"] = str(payload.get("fallback_model", "") or "").strip()
    payload["require_tool_approvals"] = _coerce_bool(
        payload.get("require_tool_approvals"),
        True,
    )
    payload["tools_enabled"] = _coerce_bool(payload.get("tools_enabled"), True)
    payload["safe_mode"] = _coerce_bool(payload.get("safe_mode"), True)
    payload["llm_provider"] = _coerce_provider(payload.get("llm_provider"))
    payload["provider_models"] = _coerce_provider_models(payload.get("provider_models"))
    payload["provider_fallback_models"] = _coerce_provider_models(
        payload.get("provider_fallback_models")
    )

    CONFIG_PATH.parent.mkdir(exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    APP_RUNTIME_CONFIG = payload
    return payload
