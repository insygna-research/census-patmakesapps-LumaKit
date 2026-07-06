"""Session-token auth for the LumaKit web surface.

A per-install random token is generated on first run and stored under the
user data dir. Every /api/* request and every WebSocket handshake must present
it (header ``X-LumaKit-Token`` or ``?token=`` query param). ``lumakit open``
injects the token into the launched browser URL so local UX stays one-click.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path
from urllib.parse import urlsplit

from core.paths import get_data_dir

TOKEN_FILE_NAME = "web_session_token"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

_token_cache: str | None = None


def token_file_path() -> Path:
    return get_data_dir() / TOKEN_FILE_NAME


def get_session_token() -> str:
    """Return the per-install web session token, generating it on first use."""
    global _token_cache
    if _token_cache:
        return _token_cache
    path = token_file_path()
    token = ""
    try:
        token = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        token = ""
    if not token:
        token = secrets.token_urlsafe(32)
        path.write_text(token, encoding="utf-8")
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    _token_cache = token
    return token


def is_valid_token(candidate) -> bool:
    if not candidate:
        return False
    return secrets.compare_digest(str(candidate), get_session_token())


def tokenized_url(base_url: str) -> str:
    """Append the session token to a UI URL for one-click local launch."""
    base = base_url.rstrip("/")
    return f"{base}/?token={get_session_token()}"


def task_page_url(task_id: int) -> str:
    """Tokenized link to the read-only task artifact page (§6.3)."""
    import json

    port = None
    try:
        state = json.loads((get_data_dir() / "lumakit-runtime.json").read_text(encoding="utf-8"))
        port = state.get("port")
    except Exception:
        port = None
    port = port or int(os.getenv("LUMAKIT_WEB_PORT", "7865") or 7865)
    return f"http://localhost:{port}/task/{task_id}?token={get_session_token()}"


def resolve_bind_host() -> str:
    """Bind host for the web server: loopback unless explicitly overridden."""
    host = str(os.getenv("LUMAKIT_BIND_HOST", "") or "").strip() or "127.0.0.1"
    if host not in LOOPBACK_HOSTS:
        print(
            f"[LumaKit] WARNING: LUMAKIT_BIND_HOST={host} — the web server is "
            "reachable from other machines. Every request still requires the "
            f"session token stored in {token_file_path()}. Add remote hostnames "
            "to LUMAKIT_ALLOWED_ORIGINS for browser (WebSocket) access."
        )
    return host


def origin_allowed(origin: str | None) -> bool:
    """Check a WebSocket Origin header against the allowed set.

    A missing Origin means a non-browser client — allowed, since the token is
    still required. Browser origins must be loopback, the explicit bind host,
    or listed in LUMAKIT_ALLOWED_ORIGINS (comma-separated hostnames). This
    blocks DNS-rebinding / cross-site WebSocket attempts from pages the user
    has open elsewhere.
    """
    if not origin:
        return True
    try:
        origin_host = (urlsplit(origin).hostname or "").lower()
    except ValueError:
        return False
    if not origin_host:
        return False
    if origin_host in LOOPBACK_HOSTS:
        return True
    allowed = {
        item.strip().lower()
        for item in str(os.getenv("LUMAKIT_ALLOWED_ORIGINS", "") or "").split(",")
        if item.strip()
    }
    bind_host = str(os.getenv("LUMAKIT_BIND_HOST", "") or "").strip().lower()
    if bind_host and bind_host not in {"0.0.0.0", "::"}:
        allowed.add(bind_host)
    return origin_host in allowed
