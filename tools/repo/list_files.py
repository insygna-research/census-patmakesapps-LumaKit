from __future__ import annotations

from core.paths import get_display_path, get_repo_root, resolve_repo_path


DEFAULT_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}


def get_list_files_tool():
    return {
        "name": "list_files",
        "description": (
            "List files under a directory with glob, hidden-file, and result limits. "
            "Use this for broad repo navigation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "pattern": {"type": "string", "description": "Glob pattern (default *)."},
                "recursive": {"type": "boolean", "description": "Recurse into subdirectories (default true)."},
                "include_hidden": {"type": "boolean", "description": "Include dotfiles and dot directories."},
                "max_results": {"type": "integer", "description": "Maximum files to return (default 500)."},
            },
        },
        "execute": _list_files,
    }


def _is_hidden(path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _list_files(inputs):
    target = resolve_repo_path(inputs["path"], kind="directory") if inputs.get("path") else get_repo_root()
    pattern = inputs.get("pattern") or "*"
    recursive = bool(inputs.get("recursive", True))
    include_hidden = bool(inputs.get("include_hidden", False))
    max_results = max(1, int(inputs.get("max_results") or 500))
    iterator = target.rglob(pattern) if recursive else target.glob(pattern)

    matches = []
    scanned = 0
    for path in sorted(iterator):
        scanned += 1
        if not path.is_file():
            continue
        try:
            rel_parts = path.relative_to(target).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in DEFAULT_SKIP_DIRS for part in rel_parts):
            continue
        if not include_hidden and _is_hidden(path.relative_to(target)):
            continue
        matches.append(get_display_path(path))
        if len(matches) >= max_results:
            break

    return {
        "path": get_display_path(target),
        "pattern": pattern,
        "recursive": recursive,
        "include_hidden": include_hidden,
        "scanned": scanned,
        "count": len(matches),
        "truncated": len(matches) >= max_results,
        "files": matches,
    }
