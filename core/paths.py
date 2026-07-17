from __future__ import annotations

import os
import shutil
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_data_dir: Path | None = None
_migration_done = False
_workspace_root: ContextVar[Path | None] = ContextVar("lumakit_workspace_root", default=None)

# File names that tools must never read/write even inside the workspace —
# they hold credentials (S-2/S-7).
_DENYLISTED_NAMES = {".env", "config.env", ".git-credentials", "web_session_token"}


def _allowed_external_roots() -> list[Path]:
    """Extra roots the user has explicitly opened up via LUMAKIT_ALLOW_PATHS
    (os.pathsep-separated). Off by default."""
    raw = str(os.getenv("LUMAKIT_ALLOW_PATHS", "") or "").strip()
    roots = []
    for item in raw.split(os.pathsep):
        item = item.strip()
        if item:
            roots.append(Path(item).expanduser().resolve(strict=False))
    return roots


def _is_denied_path(resolved: Path) -> bool:
    if resolved.name.lower() in _DENYLISTED_NAMES:
        return True
    # The whole user data dir (~/.lumakit/) holds tokens and config secrets.
    data_dir = (Path.home() / ".lumakit").resolve(strict=False)
    if resolved == data_dir or data_dir in resolved.parents:
        return True
    # Git config/credential files can embed remote credentials.
    if resolved.parent.name == ".git" and resolved.name.lower() in {"config", "credentials"}:
        return True
    return False


def ensure_tool_path_allowed(path: Path) -> Path:
    """Enforce the filesystem sandbox for tool-facing path resolution.

    Tools may only touch paths inside the current workspace root (or roots
    explicitly allowed via LUMAKIT_ALLOW_PATHS), and never denylisted secret
    files. Raises PermissionError with a model-correctable message.
    """
    resolved = path.resolve(strict=False)
    if _is_denied_path(resolved):
        raise PermissionError(
            f"Access to '{resolved.name}' is blocked: this path can contain "
            "secrets and is never accessible to tools."
        )
    # Safe mode off = owner opted into full machine access; only the secrets
    # denylist above still applies. Imported lazily to avoid a paths <->
    # app_runtime_config import cycle.
    from core.approval_policy import unrestricted_filesystem_active

    if unrestricted_filesystem_active():
        return path
    root = get_repo_root().resolve(strict=False)
    if resolved == root or resolved.is_relative_to(root):
        return path
    for allowed in _allowed_external_roots():
        if resolved == allowed or resolved.is_relative_to(allowed):
            return path
    raise PermissionError(
        f"Path '{resolved}' is outside the workspace '{root}'. Tools can only "
        "access files inside the workspace (set LUMAKIT_ALLOW_PATHS to allow "
        "specific extra directories)."
    )


def get_data_dir() -> Path:
    """Return the user data directory (~/.lumakit/), creating it on first call.

    On the very first call, if old data directories exist in the repo root
    but ~/.lumakit/ is fresh, migrate them automatically.
    """
    global _data_dir
    if _data_dir is None:
        _data_dir = Path.home() / ".lumakit"
        _data_dir.mkdir(exist_ok=True)
        _maybe_migrate()
    return _data_dir


def _maybe_migrate():
    """One-time migration: copy old repo-rooted data dirs into ~/.lumakit/."""
    global _migration_done
    if _migration_done:
        return
    _migration_done = True

    repo = get_repo_root()
    data = Path.home() / ".lumakit"

    # Map old repo-root paths → new data-dir paths
    migrations = {
        repo / "memory":    data / "memory",
        repo / "lumi":      data / "identity",
        repo / "instagram": data / "instagram",
    }

    # Also migrate repo-root .lumakit/ config files (telegram configs, etc.)
    # but NOT code_index.json (it's cache, will regenerate)
    old_dot = repo / ".lumakit"
    config_files = [
        "telegram_users.json",
        "telegram_owner_config.json",
        "telegram_user_config.json",
        "config.json",
    ]

    migrated_any = False

    for old_path, new_path in migrations.items():
        if old_path.exists() and old_path.is_dir() and not new_path.exists():
            shutil.copytree(str(old_path), str(new_path))
            migrated_any = True

    for fname in config_files:
        old_file = old_dot / fname
        new_file = data / fname
        if old_file.exists() and not new_file.exists():
            shutil.copy2(str(old_file), str(new_file))
            migrated_any = True

    # Migrate browser_profiles if they were already in .lumakit/
    old_profiles = old_dot / "browser_profiles"
    new_profiles = data / "browser_profiles"
    if old_profiles.exists() and old_profiles.is_dir() and not new_profiles.exists():
        shutil.copytree(str(old_profiles), str(new_profiles))
        migrated_any = True

    if migrated_any:
        print(
            f"[LumaKit] Migrated user data to {data}\n"
            "  Old data in the repo root is still intact — you can remove it "
            "once you've confirmed everything works."
        )


def get_repo_root() -> Path:
    return _workspace_root.get() or Path.cwd()


def set_workspace_root(path: str | Path):
    root = Path(path).expanduser().resolve(strict=False)
    return _workspace_root.set(root)


@contextmanager
def workspace_context(path: str | Path):
    token = set_workspace_root(path)
    try:
        yield get_repo_root()
    finally:
        _workspace_root.reset(token)


def get_display_path(path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(get_repo_root()).as_posix()
    except ValueError:
        return path.resolve(strict=False).as_posix()


def _matches_kind(path: Path, kind: str) -> bool:
    if kind == "file":
        return path.is_file()
    if kind == "directory":
        return path.is_dir()
    return path.exists()


def _normalize_relpath(value: str) -> str:
    return value.replace("\\", "/").strip().lower()


def _normalize_dotless_parts(parts: tuple[str, ...]) -> str:
    return "/".join(part.lstrip(".").lower() for part in parts)


def _score_candidate(query: str, candidate: Path) -> int:
    relative_path = candidate.relative_to(get_repo_root())
    query_path = Path(query.replace("\\", "/"))

    rel_text = relative_path.as_posix().lower()
    rel_dotless = _normalize_dotless_parts(relative_path.parts)
    query_text = _normalize_relpath(query)
    query_dotless = _normalize_dotless_parts(query_path.parts)
    query_name = query_path.name.lower()
    query_name_dotless = query_path.name.lstrip(".").lower()
    name = candidate.name.lower()
    name_dotless = candidate.name.lstrip(".").lower()

    scores = []

    if rel_text == query_text:
        scores.append(100)
    if rel_dotless == query_dotless:
        scores.append(95)
    if name == query_name:
        scores.append(90)
    if name_dotless == query_name_dotless:
        scores.append(85)
    if rel_text.endswith(f"/{query_text}") or rel_text == query_text:
        scores.append(80)
    if rel_dotless.endswith(f"/{query_dotless}") or rel_dotless == query_dotless:
        scores.append(75)

    return max(scores, default=0)


def _iter_repo_paths(kind: str):
    root = get_repo_root()
    for path in root.rglob("*"):
        if _matches_kind(path, kind):
            yield path


def resolve_repo_path(raw_path: str, *, must_exist: bool = True, kind: str = "file") -> Path:
    if not raw_path or not str(raw_path).strip():
        raise ValueError("Path must not be empty")

    requested = Path(str(raw_path).strip())
    root = get_repo_root()
    direct_candidates = []

    if requested.is_absolute():
        direct_candidates.append(requested)
        if requested.name and not requested.name.startswith("."):
            direct_candidates.append(requested.with_name(f".{requested.name}"))
    else:
        direct_candidates.append(root / requested)
        if requested.name and not requested.name.startswith("."):
            direct_candidates.append(root / requested.with_name(f".{requested.name}"))

    for candidate in direct_candidates:
        if candidate.exists() and _matches_kind(candidate, kind):
            return ensure_tool_path_allowed(candidate.resolve())

    scored_matches = []
    for candidate in _iter_repo_paths(kind):
        score = _score_candidate(str(requested), candidate)
        if score > 0:
            scored_matches.append((score, candidate.resolve()))

    if scored_matches:
        scored_matches.sort(key=lambda item: (-item[0], get_display_path(item[1])))
        best_score = scored_matches[0][0]
        best_matches = [path for score, path in scored_matches if score == best_score]
        if len(best_matches) == 1:
            return ensure_tool_path_allowed(best_matches[0])
        options = ", ".join(get_display_path(path) for path in best_matches[:5])
        raise FileNotFoundError(f"Ambiguous path '{raw_path}'. Matches: {options}")

    if must_exist:
        raise FileNotFoundError(f"Could not resolve path '{raw_path}' from {root}")

    return ensure_tool_path_allowed(direct_candidates[0].resolve(strict=False))
