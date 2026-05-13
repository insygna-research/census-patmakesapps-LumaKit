from __future__ import annotations

import json
import shutil
import subprocess

from core.paths import get_display_path, get_repo_root, resolve_repo_path


def get_rg_search_tool():
    return {
        "name": "rg_search",
        "description": (
            "Fast text search powered by ripgrep when available, with a Python fallback. "
            "Returns file, line number, and matching line preview."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {
                    "type": "string",
                    "description": "Directory or file to search (default workspace root).",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional glob filter, e.g. *.py.",
                },
                "regex": {
                    "type": "boolean",
                    "description": "Treat query as regex (default false).",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case-sensitive search (default false).",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 100).",
                },
            },
            "required": ["query"],
        },
        "execute": _rg_search,
    }


def _target_path(raw):
    if raw:
        try:
            return resolve_repo_path(raw, kind="directory")
        except Exception:
            return resolve_repo_path(raw, kind="file")
    return get_repo_root()


def _rg_search(inputs):
    query = str(inputs["query"])
    target = _target_path(inputs.get("path"))
    max_results = max(1, int(inputs.get("max_results") or 100))
    rg = shutil.which("rg")
    if rg:
        return _search_with_rg(rg, query, target, inputs, max_results)
    return _search_with_python(query, target, inputs, max_results)


def _search_with_rg(rg, query, target, inputs, max_results):
    args = [
        rg,
        "--json",
        "--line-number",
        "--no-heading",
        "--hidden",
        "--glob",
        "!**/.git/**",
        "--glob",
        "!**/node_modules/**",
    ]
    if not bool(inputs.get("regex", False)):
        args.append("--fixed-strings")
    if not bool(inputs.get("case_sensitive", False)):
        args.append("--ignore-case")
    if inputs.get("glob"):
        args.extend(["--glob", str(inputs["glob"])])
    args.extend([query, str(target)])

    result = subprocess.run(
        args,
        cwd=get_repo_root(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    matches = []
    for raw_line in result.stdout.splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        path_text = data.get("path", {}).get("text", "")
        line_text = data.get("lines", {}).get("text", "").rstrip("\r\n")
        matches.append(
            {
                "path": (
                    get_display_path((get_repo_root() / path_text).resolve())
                    if path_text
                    else ""
                ),
                "line": data.get("line_number"),
                "content": line_text,
            }
        )
        if len(matches) >= max_results:
            break

    if result.returncode not in (0, 1):
        return {
            "query": query,
            "path": get_display_path(target),
            "success": False,
            "error": result.stderr.strip() or "ripgrep failed",
            "returncode": result.returncode,
            "matches": matches,
        }

    return {
        "query": query,
        "path": get_display_path(target),
        "engine": "rg",
        "count": len(matches),
        "truncated": len(matches) >= max_results,
        "matches": matches,
    }


def _search_with_python(query, target, inputs, max_results):
    needle = query if bool(inputs.get("case_sensitive", False)) else query.lower()
    glob = inputs.get("glob") or "*"
    iterator = [target] if target.is_file() else target.rglob(glob)
    matches = []
    scanned = 0
    for path in sorted(iterator):
        if not path.is_file():
            continue
        if any(part in {".git", "node_modules", "__pycache__"} for part in path.parts):
            continue
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            haystack = (
                line if bool(inputs.get("case_sensitive", False)) else line.lower()
            )
            if needle in haystack:
                matches.append(
                    {
                        "path": get_display_path(path),
                        "line": line_number,
                        "content": line,
                    }
                )
                if len(matches) >= max_results:
                    return {
                        "query": query,
                        "path": get_display_path(target),
                        "engine": "python",
                        "scanned_files": scanned,
                        "count": len(matches),
                        "truncated": True,
                        "matches": matches,
                    }

    return {
        "query": query,
        "path": get_display_path(target),
        "engine": "python",
        "scanned_files": scanned,
        "count": len(matches),
        "truncated": False,
        "matches": matches,
    }
