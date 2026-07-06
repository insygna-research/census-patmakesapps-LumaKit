from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from core.diffs import build_unified_diff, detect_line_ending, normalize_line_endings
from core.paths import ensure_tool_path_allowed, get_display_path, get_repo_root


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)


@dataclass
class FilePatch:
    old_path: str | None = None
    new_path: str | None = None
    hunks: list[Hunk] = field(default_factory=list)


def get_apply_patch_tool():
    return {
        "name": "apply_patch",
        "description": (
            "Apply a unified diff patch across one or more files. Supports updates, "
            "new files, and deletions. Returns changed files and a resulting diff."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "patch": {"type": "string", "description": "Unified diff text."},
                "dry_run": {
                    "type": "boolean",
                    "description": "Validate and preview without writing files.",
                },
            },
            "required": ["patch"],
        },
        "execute": _apply_patch_tool,
    }


def _strip_prefix(path: str | None) -> str | None:
    if not path or path == "/dev/null":
        return None
    path = path.strip()
    if "\t" in path:
        path = path.split("\t", 1)[0]
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _parse_header_path(line: str) -> str | None:
    return _strip_prefix(line[4:].strip())


def _parse_patch(patch_text: str) -> list[FilePatch]:
    patches: list[FilePatch] = []
    current: FilePatch | None = None
    current_hunk: Hunk | None = None
    hunk_re = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

    for raw_line in patch_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith("diff --git "):
            if current and (current.old_path or current.new_path or current.hunks):
                patches.append(current)
            current = FilePatch()
            current_hunk = None
            parts = raw_line.split()
            if len(parts) >= 4:
                current.old_path = _strip_prefix(parts[2])
                current.new_path = _strip_prefix(parts[3])
            continue
        if raw_line.startswith("--- "):
            if current is None:
                current = FilePatch()
            current.old_path = _parse_header_path(raw_line)
            continue
        if raw_line.startswith("+++ "):
            if current is None:
                current = FilePatch()
            current.new_path = _parse_header_path(raw_line)
            continue
        match = hunk_re.match(raw_line)
        if match:
            if current is None:
                current = FilePatch()
            current_hunk = Hunk(
                old_start=int(match.group(1)),
                old_count=int(match.group(2) or "1"),
                new_start=int(match.group(3)),
                new_count=int(match.group(4) or "1"),
            )
            current.hunks.append(current_hunk)
            continue
        if current_hunk is not None:
            if raw_line.startswith((" ", "+", "-")):
                current_hunk.lines.append(raw_line)
            elif raw_line.startswith("\\ No newline"):
                continue

    if current and (current.old_path or current.new_path or current.hunks):
        patches.append(current)

    valid = [item for item in patches if item.hunks and (item.old_path or item.new_path)]
    if not valid:
        raise ValueError("No unified-diff file hunks were found in patch")
    return valid


def _resolve_patch_path(path: str | None) -> Path | None:
    if path is None:
        return None
    candidate = Path(path)
    if candidate.is_absolute():
        return ensure_tool_path_allowed(candidate.resolve())
    return ensure_tool_path_allowed((get_repo_root() / candidate).resolve(strict=False))


def _find_sequence(lines: list[str], sequence: list[str], start_index: int) -> int | None:
    if not sequence:
        return start_index
    if lines[start_index:start_index + len(sequence)] == sequence:
        return start_index
    max_start = len(lines) - len(sequence)
    for idx in range(max_start + 1):
        if lines[idx:idx + len(sequence)] == sequence:
            return idx
    return None


def _apply_hunks(original: str, file_patch: FilePatch) -> str:
    lines = original.splitlines()
    offset = 0
    for hunk in file_patch.hunks:
        old_sequence = [line[1:] for line in hunk.lines if line[:1] in {" ", "-"}]
        new_sequence = [line[1:] for line in hunk.lines if line[:1] in {" ", "+"}]
        expected = max(0, hunk.old_start - 1 + offset)
        found = _find_sequence(lines, old_sequence, expected)
        if found is None:
            target = file_patch.new_path or file_patch.old_path or "<unknown>"
            raise ValueError(f"Patch hunk did not apply cleanly to {target} near line {hunk.old_start}")
        lines[found:found + len(old_sequence)] = new_sequence
        offset += len(new_sequence) - len(old_sequence)
    newline = detect_line_ending(original) if original else "\n"
    if not lines:
        return ""
    return normalize_line_endings("\n".join(lines) + "\n", newline)


def _apply_patch_tool(inputs):
    patch_text = str(inputs["patch"])
    dry_run = bool(inputs.get("dry_run", False))
    file_patches = _parse_patch(patch_text)
    changed_files = []
    combined_diff_parts = []

    for file_patch in file_patches:
        old_path = _resolve_patch_path(file_patch.old_path)
        new_path = _resolve_patch_path(file_patch.new_path)
        target_path = new_path or old_path
        if target_path is None:
            raise ValueError("Patch file target could not be resolved")

        before = ""
        existed_before = old_path.exists() if old_path else False
        if old_path and old_path.exists():
            before = old_path.read_text(encoding="utf-8", errors="replace")
        elif file_patch.old_path is not None:
            raise FileNotFoundError(f"Patch target does not exist: {get_display_path(old_path)}")

        after = _apply_hunks(before, file_patch)
        delete_file = file_patch.new_path is None and after == ""
        diff_target = target_path
        diff_data = build_unified_diff(before, "" if delete_file else after, diff_target)
        if diff_data.get("diff"):
            combined_diff_parts.append(diff_data["diff"])

        changed_files.append({
            "path": get_display_path(target_path),
            "old_path": get_display_path(old_path) if old_path else None,
            "created": not existed_before and not delete_file,
            "deleted": delete_file,
            "renamed": bool(old_path and new_path and old_path != new_path),
            "changed": before != after or delete_file,
        })

        if dry_run:
            continue

        if delete_file:
            if target_path.exists():
                target_path.unlink()
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(after, encoding="utf-8")
        if old_path and new_path and old_path != new_path and old_path.exists():
            old_path.unlink()

    return {
        "dry_run": dry_run,
        "changed_files": changed_files,
        "count": len(changed_files),
        "diff": "\n".join(part for part in combined_diff_parts if part),
        "has_changes": bool(combined_diff_parts),
    }
