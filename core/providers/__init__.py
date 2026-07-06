"""Provider factory — pick the LLM backend from config.

Providers: ``ollama`` (default, local privacy option — keeps the native
OllamaClient with its priority-gated local scheduler), ``anthropic`` (Claude),
``openai`` (GPT), ``xai`` (Grok). The latter two share one OpenAI-compatible
adapter with different base URLs.

Resolution order for the provider: app runtime config (Settings UI) →
``LLM_PROVIDER`` env → ``ollama``. The old ``OLLAMA_*`` env vars keep working
as aliases for provider=ollama.
"""

from __future__ import annotations

import os

from core.providers.base import (
    LLMClient,
    ProviderConnectionError,
    ProviderInterruptedError,
    ProviderTimeoutError,
)

VALID_PROVIDERS = ("ollama", "anthropic", "openai", "xai")

_DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "xai": "https://api.x.ai/v1",
    "ollama": "http://localhost:11434",
}

_PROVIDER_KEY_ENVS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "xai": "XAI_API_KEY",
}


def resolve_provider_name() -> str:
    try:
        from core.app_runtime_config import get_app_runtime_config

        configured = str(get_app_runtime_config().get("llm_provider", "") or "").strip().lower()
    except Exception:
        configured = ""
    provider = configured or str(os.getenv("LLM_PROVIDER", "") or "").strip().lower() or "ollama"
    return provider if provider in VALID_PROVIDERS else "ollama"


def resolve_api_key(provider: str | None = None) -> str | None:
    provider = provider or resolve_provider_name()
    key = str(os.getenv("LLM_API_KEY", "") or "").strip()
    if not key:
        env_name = _PROVIDER_KEY_ENVS.get(provider)
        if env_name:
            key = str(os.getenv(env_name, "") or "").strip()
    return key or None


def default_model() -> str:
    return str(os.getenv("LLM_MODEL", "") or os.getenv("OLLAMA_MODEL", "") or "").strip()


def default_fallback_model() -> str:
    return str(
        os.getenv("LLM_FALLBACK_MODEL", "") or os.getenv("OLLAMA_FALLBACK_MODEL", "") or ""
    ).strip()


def save_api_key(key: str) -> None:
    """Persist the LLM API key server-side (never echoed back to clients).

    Written to ~/.lumakit/config.env, which is loaded at boot and is on the
    S-2 filesystem denylist so file tools can never read it.
    """
    import re
    import stat

    from core.paths import get_data_dir

    key = str(key or "").strip()
    if not key:
        return
    config_path = get_data_dir() / "config.env"
    try:
        existing = config_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        existing = ""
    line = f'LLM_API_KEY="{key}"'
    if re.search(r"^LLM_API_KEY=.*$", existing, flags=re.MULTILINE):
        updated = re.sub(r"^LLM_API_KEY=.*$", line, existing, flags=re.MULTILINE)
    else:
        updated = existing.rstrip("\n")
        updated = (updated + "\n" if updated else "") + line + "\n"
    config_path.write_text(updated, encoding="utf-8")
    try:
        os.chmod(config_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.environ["LLM_API_KEY"] = key


def api_key_is_set(provider: str | None = None) -> bool:
    return bool(resolve_api_key(provider))


def create_llm_client(*, fallback_model=None, request_timeout: int = 120) -> LLMClient:
    """Create the configured provider client with the shared chat() surface."""
    provider = resolve_provider_name()
    if fallback_model is None:
        fallback_model = default_fallback_model() or None
    base_url = str(os.getenv("LLM_BASE_URL", "") or "").strip() or None

    if provider == "anthropic":
        from core.providers.anthropic_provider import AnthropicClient

        return AnthropicClient(
            api_key=resolve_api_key(provider),
            base_url=base_url,
            fallback_model=fallback_model,
            request_timeout=request_timeout,
        )

    if provider in ("openai", "xai"):
        from core.providers.openai_compat import OpenAICompatClient

        return OpenAICompatClient(
            base_url=base_url or _DEFAULT_BASE_URLS[provider],
            api_key=resolve_api_key(provider),
            provider_name=provider,
            fallback_model=fallback_model,
            request_timeout=request_timeout,
        )

    # Default: local Ollama via its native client (keeps the local scheduler).
    from ollama_client import OllamaClient

    return OllamaClient(
        base_url=base_url or _DEFAULT_BASE_URLS["ollama"],
        fallback_model=fallback_model,
        request_timeout=request_timeout,
    )
