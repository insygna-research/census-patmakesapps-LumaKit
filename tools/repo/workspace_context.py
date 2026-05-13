from __future__ import annotations

import os
import subprocess
from pathlib import Path

from core.paths import get_data_dir, get_display_path, get_repo_root, set_workspace_root


def get_workspace_context_tool():
    return {
        "name": "workspace_context",
        "description": (
            "Return the active workspace model: cwd, git root, branch, home/data directories, "
            "and path-resolution rules used by repo tools."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "execute": _workspace_context,
    }


def get_set_workspace_tool():
    return {
        "name": "set_workspace",
        "description": (
            "Change LumaKit's active working directory. After this, relative repo-tool "
            "paths resolve from the new workspace."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to use as the active workspace."}
            },
            "required": ["path"],
        },
        "execute": _set_workspace,
    }


def _run_git(args):
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=get_repo_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _workspace_context(inputs):
    cwd = get_repo_root()
    git_root = _run_git(["rev-parse", "--show-toplevel"])
    branch = _run_git(["branch", "--show-current"])
    return {
        "cwd": str(cwd),
        "cwd_display": get_display_path(cwd),
        "home": str(Path.home()),
        "data_dir": str(get_data_dir()),
        "inside_git": bool(git_root),
        "git_root": git_root,
        "git_branch": branch,
        "path_resolution": {
            "relative_paths": "Resolved against the current LumaKit process working directory.",
            "absolute_paths": "Accepted by repo tools when supplied.",
            "display_paths": "Paths inside cwd are shown relative; outside paths are shown absolute.",
        },
        "environment": {
            "platform": os.name,
            "python": os.environ.get("PYTHONPATH", ""),
        },
    }


def _set_workspace(inputs):
    raw_path = Path(str(inputs["path"])).expanduser()
    if not raw_path.is_absolute():
        raw_path = get_repo_root() / raw_path
    path = raw_path.resolve(strict=False)
    if not path.exists():
        raise FileNotFoundError(f"Workspace does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Workspace is not a directory: {path}")
    set_workspace_root(path)
    return _workspace_context({})
