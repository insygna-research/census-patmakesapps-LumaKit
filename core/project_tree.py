"""ASCII project-tree rendering (extracted from agent.py, D-1)."""

from __future__ import annotations

from pathlib import Path


def build_project_tree(root: Path, max_depth: int = 3) -> str:
    lines = []
    skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".env"}

    def _walk(directory: Path, prefix: str, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(
                directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
        except PermissionError:
            return
        dirs = [e for e in entries if e.is_dir() and e.name not in skip]
        files = [e for e in entries if e.is_file()]
        items = dirs + files
        for i, entry in enumerate(items):
            connector = "└── " if i == len(items) - 1 else "├── "
            lines.append(
                f"{prefix}{connector}{entry.name}{'/' if entry.is_dir() else ''}"
            )
            if entry.is_dir():
                extension = "    " if i == len(items) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    lines.append(f"{root.name}/")
    _walk(root, "", 1)
    return "\n".join(lines)
