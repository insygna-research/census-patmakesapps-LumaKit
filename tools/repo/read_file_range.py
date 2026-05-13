from __future__ import annotations

from core.paths import get_display_path, resolve_repo_path


def get_read_file_range_tool():
    return {
        "name": "read_file_range",
        "description": (
            "Read a specific line range from a file. Use this instead of read_file "
            "when only part of a large file is needed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "description": "1-based first line (default 1)."},
                "end_line": {"type": "integer", "description": "1-based final line, inclusive."},
                "line_count": {
                    "type": "integer",
                    "description": "Number of lines to read if end_line is omitted (default 120).",
                },
                "include_line_numbers": {
                    "type": "boolean",
                    "description": "Prefix each returned line with its line number (default true).",
                },
            },
            "required": ["path"],
        },
        "execute": _read_file_range,
    }


def _read_file_range(inputs):
    path = resolve_repo_path(inputs["path"], kind="file")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    start = max(1, int(inputs.get("start_line") or 1))
    if inputs.get("end_line") is not None:
        end = int(inputs["end_line"])
    else:
        end = start + int(inputs.get("line_count") or 120) - 1
    end = max(start, min(end, total))
    include_numbers = bool(inputs.get("include_line_numbers", True))

    selected = lines[start - 1:end]
    if include_numbers:
        width = len(str(end))
        content = "\n".join(
            f"{line_no:>{width}}: {line}"
            for line_no, line in enumerate(selected, start=start)
        )
    else:
        content = "\n".join(selected)

    return {
        "path": get_display_path(path),
        "start_line": start,
        "end_line": end,
        "total_lines": total,
        "content": content,
        "truncated": end < total,
    }
