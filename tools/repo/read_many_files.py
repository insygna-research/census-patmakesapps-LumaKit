from __future__ import annotations

from core.paths import get_display_path, resolve_repo_path


def get_read_many_files_tool():
    return {
        "name": "read_many_files",
        "description": (
            "Read multiple files in one tool call with per-file and total size limits. "
            "Useful after search results identify several relevant files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "max_chars_per_file": {
                    "type": "integer",
                    "description": "Maximum characters returned per file (default 12000).",
                },
                "max_total_chars": {
                    "type": "integer",
                    "description": "Maximum total characters returned (default 50000).",
                },
            },
            "required": ["paths"],
        },
        "execute": _read_many_files,
    }


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n... [file truncated]", True


def _read_many_files(inputs):
    paths = inputs.get("paths") or []
    if not isinstance(paths, list) or not paths:
        raise ValueError("paths must be a non-empty array")

    per_file_limit = max(1000, int(inputs.get("max_chars_per_file") or 12000))
    total_limit = max(1000, int(inputs.get("max_total_chars") or 50000))
    total_used = 0
    files = []

    for raw_path in paths:
        path = resolve_repo_path(str(raw_path), kind="file")
        text = path.read_text(encoding="utf-8", errors="replace")
        remaining = max(0, total_limit - total_used)
        if remaining <= 0:
            files.append({
                "path": get_display_path(path),
                "content": "",
                "truncated": True,
                "skipped": True,
                "reason": "max_total_chars reached",
            })
            continue
        content, truncated = _clip(text, min(per_file_limit, remaining))
        total_used += len(content)
        files.append({
            "path": get_display_path(path),
            "size": path.stat().st_size,
            "content": content,
            "truncated": truncated or len(text) > remaining,
        })

    return {
        "count": len(files),
        "max_chars_per_file": per_file_limit,
        "max_total_chars": total_limit,
        "chars_returned": total_used,
        "files": files,
    }
