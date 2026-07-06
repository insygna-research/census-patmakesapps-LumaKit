"""Diff previews for file-modifying tools (D-1).

Computes what edit_file/write_file/delete_file would do WITHOUT writing, so
the approval flow can show a diff before anything changes on disk.
"""

from __future__ import annotations

from core.diffs import build_unified_diff, detect_line_ending, normalize_line_endings
from core.paths import resolve_repo_path


def preview_edit(inputs: dict) -> dict | None:
    """Compute what edit_file would produce without writing. Returns diff info or None."""
    try:
        path = resolve_repo_path(inputs["path"], kind="file")
    except (FileNotFoundError, ValueError):
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    newline = detect_line_ending(content)
    find_text = normalize_line_endings(inputs["find"], newline)
    replace_text = normalize_line_endings(inputs["replace"], newline)
    if find_text not in content:
        return None
    replace_all = bool(inputs.get("replace_all", False))
    updated = (
        content.replace(find_text, replace_text)
        if replace_all
        else content.replace(find_text, replace_text, 1)
    )
    return build_unified_diff(content, updated, path)


def preview_write(inputs: dict) -> dict | None:
    """Compute what write_file would produce without writing. Returns diff info."""
    try:
        path = resolve_repo_path(inputs["path"], must_exist=False, kind="file")
    except ValueError:
        return None
    is_new = not path.exists()
    before = path.read_text(encoding="utf-8", errors="replace") if not is_new else ""
    preferred_newline = detect_line_ending(before) if before else "\n"
    after = normalize_line_endings(inputs["content"], preferred_newline)
    result = build_unified_diff(before, after, path)
    if result is not None:
        result["is_new"] = is_new
    return result


def preview_delete(inputs: dict) -> dict | None:
    """Compute what delete_file would show. Returns diff info."""
    try:
        path = resolve_repo_path(inputs["path"], kind="file")
    except (FileNotFoundError, ValueError):
        return None
    before = path.read_text(encoding="utf-8", errors="replace")
    return build_unified_diff(before, "", path)
