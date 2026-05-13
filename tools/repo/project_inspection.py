from __future__ import annotations

import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from core.paths import get_display_path, get_repo_root, resolve_repo_path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None


SKIP_DIRS = {
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
    ".next",
}

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".kt": "kotlin",
    ".html": "html",
    ".css": "css",
}


def get_inspect_project_tool():
    return {
        "name": "inspect_project",
        "description": (
            "Inspect a project and infer languages, package manager, frameworks, "
            "entry points, git state, and likely test/build/lint/dev commands."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project directory (default current workspace)."},
                "max_files": {"type": "integer", "description": "Max files to scan (default 3000)."},
                "include_git": {"type": "boolean", "description": "Include git state (default true)."},
            },
        },
        "execute": _inspect_project,
    }


def _run(args: list[str], cwd: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except Exception as exc:
        return {"success": False, "stdout": "", "stderr": str(exc), "returncode": None}


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_toml(path: Path) -> dict:
    if tomllib is None:
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _iter_files(root: Path, max_files: int):
    count = 0
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        yield path
        count += 1
        if count >= max_files:
            return


def _detect_package_manager(root: Path) -> str | None:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "package-lock.json").exists():
        return "npm"
    if (root / "uv.lock").exists():
        return "uv"
    if (root / "poetry.lock").exists():
        return "poetry"
    if (root / "Pipfile.lock").exists():
        return "pipenv"
    if (root / "Cargo.lock").exists():
        return "cargo"
    if (root / "go.mod").exists():
        return "go"
    return None


def _package_script_command(manager: str | None, script: str) -> str:
    if manager == "pnpm":
        return f"pnpm {script}"
    if manager == "yarn":
        return f"yarn {script}"
    if manager == "npm":
        return f"npm run {script}"
    return f"npm run {script}"


def _detect_js(root: Path, commands: list[dict], frameworks: set[str], key_files: list[str]):
    package_json = root / "package.json"
    if not package_json.exists():
        return
    key_files.append(get_display_path(package_json))
    package = _load_json(package_json)
    manager = _detect_package_manager(root) or "npm"
    scripts = package.get("scripts") or {}
    deps = {}
    deps.update(package.get("dependencies") or {})
    deps.update(package.get("devDependencies") or {})

    for name in ("next", "react", "vue", "svelte", "vite", "astro", "expo", "electron"):
        if name in deps:
            frameworks.add(name)

    for script in ("test", "build", "lint", "typecheck", "check", "dev", "start"):
        if script in scripts:
            kind = "dev_server" if script in {"dev", "start"} else script
            commands.append({
                "kind": kind,
                "command": _package_script_command(manager, script),
                "source": "package.json",
            })


def _detect_python(root: Path, commands: list[dict], frameworks: set[str], key_files: list[str]):
    pyproject = root / "pyproject.toml"
    requirements = root / "requirements.txt"
    manage_py = root / "manage.py"
    if pyproject.exists():
        key_files.append(get_display_path(pyproject))
        data = _load_toml(pyproject)
        deps = str(data).lower()
        if "pytest" in deps or (root / "pytest.ini").exists():
            commands.append({"kind": "test", "command": "python -m pytest", "source": "pyproject.toml"})
        if "ruff" in deps:
            commands.append({"kind": "lint", "command": "python -m ruff check .", "source": "pyproject.toml"})
        if "mypy" in deps:
            commands.append({"kind": "typecheck", "command": "python -m mypy .", "source": "pyproject.toml"})
        for name in ("fastapi", "django", "flask", "pytest", "ruff", "mypy"):
            if name in deps:
                frameworks.add(name)
    if requirements.exists():
        key_files.append(get_display_path(requirements))
        text = requirements.read_text(encoding="utf-8", errors="ignore").lower()
        for name in ("fastapi", "django", "flask", "pytest"):
            if name in text:
                frameworks.add(name)
        if "pytest" in text and not any(cmd["command"] == "python -m pytest" for cmd in commands):
            commands.append({"kind": "test", "command": "python -m pytest", "source": "requirements.txt"})
    if manage_py.exists():
        key_files.append(get_display_path(manage_py))
        frameworks.add("django")
        commands.append({"kind": "test", "command": "python manage.py test", "source": "manage.py"})


def _detect_other(root: Path, commands: list[dict], key_files: list[str]):
    if (root / "Cargo.toml").exists():
        key_files.append(get_display_path(root / "Cargo.toml"))
        commands.extend([
            {"kind": "test", "command": "cargo test", "source": "Cargo.toml"},
            {"kind": "build", "command": "cargo build", "source": "Cargo.toml"},
        ])
    if (root / "go.mod").exists():
        key_files.append(get_display_path(root / "go.mod"))
        commands.extend([
            {"kind": "test", "command": "go test ./...", "source": "go.mod"},
            {"kind": "build", "command": "go build ./...", "source": "go.mod"},
        ])


def _git_info(root: Path) -> dict:
    inside = _run(["git", "rev-parse", "--is-inside-work-tree"], root)
    if not inside["success"]:
        return {"inside_git": False}
    git_root = _run(["git", "rev-parse", "--show-toplevel"], root)
    branch = _run(["git", "branch", "--show-current"], root)
    status = _run(["git", "status", "--short", "--branch"], root)
    return {
        "inside_git": True,
        "git_root": git_root["stdout"] if git_root["success"] else None,
        "branch": branch["stdout"] if branch["success"] else None,
        "status": status["stdout"].splitlines() if status["success"] else [],
    }


def _dedupe_commands(commands: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for command in commands:
        key = (command.get("kind"), command.get("command"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(command)
    return unique


def _inspect_project(inputs):
    root = resolve_repo_path(inputs["path"], kind="directory") if inputs.get("path") else get_repo_root()
    max_files = max(100, int(inputs.get("max_files") or 3000))
    include_git = bool(inputs.get("include_git", True))

    files = list(_iter_files(root, max_files))
    ext_counts = Counter(path.suffix.lower() or "<no_ext>" for path in files)
    language_counts = Counter(
        LANG_BY_EXT[path.suffix.lower()]
        for path in files
        if path.suffix.lower() in LANG_BY_EXT
    )

    commands: list[dict] = []
    frameworks: set[str] = set()
    key_files: list[str] = []
    _detect_js(root, commands, frameworks, key_files)
    _detect_python(root, commands, frameworks, key_files)
    _detect_other(root, commands, key_files)

    for name in (
        "README.md",
        ".env.example",
        "docker-compose.yml",
        "Dockerfile",
        "Makefile",
        "tsconfig.json",
        "vite.config.ts",
        "next.config.js",
        "pytest.ini",
    ):
        path = root / name
        if path.exists() and get_display_path(path) not in key_files:
            key_files.append(get_display_path(path))

    return {
        "root": get_display_path(root),
        "absolute_root": str(root),
        "package_manager": _detect_package_manager(root),
        "languages": dict(language_counts.most_common()),
        "file_extensions": dict(ext_counts.most_common(20)),
        "files_scanned": len(files),
        "scan_truncated": len(files) >= max_files,
        "frameworks": sorted(frameworks),
        "key_files": key_files,
        "commands": _dedupe_commands(commands),
        "git": _git_info(root) if include_git else None,
    }
