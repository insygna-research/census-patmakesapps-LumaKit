"""Backend restart coordination + config-drift detection (plan §6.3).

Two related problems, one module:

1. The backend loads `.env` / `~/.lumakit/config.env` once at startup, so
   keys or config edited on disk while it's running are silently invisible
   until a restart. `env_drift()` reports which watched variables differ
   between disk and the running process, so the UI can tell the user a
   restart is needed (names only — values are never exposed).

2. `lumakit serve` registers a shutdown hook here so the token-gated
   `POST /api/restart` route can trigger a graceful stop; after the server
   drains, the serve loop checks `restart_requested()` and respawns the
   daemon. The web layer never imports the launcher.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from core.paths import get_data_dir

# Vars whose on-disk edits require a process restart to take effect.
# Extend this list when a new startup-only setting is added.
WATCHED_ENV_VARS = (
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_FALLBACK_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "XAI_API_KEY",
    "OLLAMA_MODEL",
    "OLLAMA_FALLBACK_MODEL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_IDS",
    "LUMAKIT_BIND_HOST",
    "LUMAKIT_WEB_PORT",
    "LUMAKIT_ALLOWED_ORIGINS",
    "LUMAKIT_ALLOW_PATHS",
)

_REPO_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

_RESTART_EVENT = threading.Event()
_SHUTDOWN_HOOK = None
_HOOK_LOCK = threading.Lock()

# Delay before triggering shutdown so the /api/restart HTTP response can
# flush to the browser first.
_SHUTDOWN_DELAY_SECONDS = 0.75


def register_shutdown_hook(hook) -> None:
    """Called by the serve loop with a zero-arg callable that begins a
    graceful shutdown (sets server.should_exit)."""
    global _SHUTDOWN_HOOK
    with _HOOK_LOCK:
        _SHUTDOWN_HOOK = hook


def restart_supported() -> bool:
    with _HOOK_LOCK:
        return _SHUTDOWN_HOOK is not None


def restart_requested() -> bool:
    return _RESTART_EVENT.is_set()


def schedule_restart() -> bool:
    """Arrange a graceful shutdown-with-restart. Returns False when no
    shutdown hook is registered (unsupported run mode)."""
    with _HOOK_LOCK:
        hook = _SHUTDOWN_HOOK
    if hook is None:
        return False
    _RESTART_EVENT.set()

    def _fire():
        try:
            hook()
        except Exception:
            _RESTART_EVENT.clear()

    threading.Timer(_SHUTDOWN_DELAY_SECONDS, _fire).start()
    return True


def _expected_env_from_disk() -> dict:
    """Merge .env + config.env the way the launcher loads them.

    lumakit.py loads config.env first, then .env, with override=False —
    so config.env wins over .env, and pre-existing process env wins over
    both. Mirror that: .env values overlaid by config.env values.
    """
    from dotenv import dotenv_values

    repo_env = _REPO_ENV_PATH
    user_env = get_data_dir() / "config.env"

    merged: dict = {}
    for path in (repo_env, user_env):
        try:
            if path.exists():
                merged.update({
                    k: v for k, v in dotenv_values(path).items() if v is not None
                })
        except OSError:
            continue
    return merged


def env_drift() -> list[str]:
    """Names of watched vars whose on-disk value differs from the running
    process. Values are never returned — the list feeds a UI notice only."""
    disk = _expected_env_from_disk()
    drifted = []
    for name in WATCHED_ENV_VARS:
        disk_value = (disk.get(name) or "").strip()
        if not disk_value:
            continue
        if disk_value != (os.environ.get(name) or "").strip():
            drifted.append(name)
    return drifted
