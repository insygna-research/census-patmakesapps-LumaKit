from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from core.interrupts import OperationInterrupted, raise_if_interrupted
from core.paths import get_display_path, get_repo_root


_BACKGROUND_PROCS: dict[str, dict[str, Any]] = {}


def get_run_command_tool():
    return {
        "name": "run_command",
        "description": (
            "Run a command for coding workflows such as tests, builds, linters, "
            "and dev servers. Supports cwd, env, timeout, output limits, and background mode."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run."},
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argument vector to run without a shell. Overrides command if provided.",
                },
                "cwd": {"type": "string", "description": "Working directory (default current workspace)."},
                "env": {"type": "object", "description": "Environment variables to add or override."},
                "timeout": {"type": "number", "description": "Timeout in seconds (default 600)."},
                "max_output_chars": {
                    "type": "integer",
                    "description": "Maximum stdout/stderr characters returned (default 12000).",
                },
                "background": {
                    "type": "boolean",
                    "description": "Start the command and return immediately (for dev servers).",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why this command needs to run.",
                },
            },
            "required": ["reason"],
        },
        "execute": _run_command,
    }


def get_list_background_commands_tool():
    return {
        "name": "list_background_commands",
        "description": "List background commands started with run_command(background=true).",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "execute": _list_background_commands,
    }


def get_read_background_command_tool():
    return {
        "name": "read_background_command",
        "description": "Read current stdout/stderr and status for a background command.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "process_id": {"type": "string"},
                "max_output_chars": {"type": "integer", "description": "Output limit (default 12000)."},
            },
            "required": ["process_id"],
        },
        "execute": _read_background_command,
    }


def get_stop_background_command_tool():
    return {
        "name": "stop_background_command",
        "description": "Stop a background command started with run_command(background=true).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "process_id": {"type": "string"},
                "reason": {"type": "string", "description": "Why this process should be stopped."},
            },
            "required": ["process_id"],
        },
        "execute": _stop_background_command,
    }


def _resolve_cwd(raw: str | None) -> Path:
    if raw:
        path = Path(str(raw))
        if not path.is_absolute():
            path = get_repo_root() / path
        return path.resolve(strict=False)
    return get_repo_root()


def _command_from_inputs(inputs) -> tuple[str | list[str], bool, str]:
    args = inputs.get("args")
    if isinstance(args, list) and args:
        command = [str(part) for part in args]
        return command, False, " ".join(command)
    command_text = str(inputs.get("command") or "").strip()
    if not command_text:
        raise ValueError("Either command or args must be provided")
    return command_text, True, command_text


def _merged_env(inputs) -> dict[str, str]:
    env = dict(os.environ)
    for key, value in (inputs.get("env") or {}).items():
        env[str(key)] = str(value)
    return env


def _clip_output(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    keep_head = max(0, limit // 3)
    keep_tail = max(0, limit - keep_head)
    return (
        text[:keep_head]
        + "\n... [output truncated] ...\n"
        + text[-keep_tail:],
        True,
    )


def _tail_lines(text: str, limit: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-limit:])


def _terminate_process(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        pass
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except Exception:
        pass


def _run_command(inputs):
    command, shell, command_text = _command_from_inputs(inputs)
    cwd = _resolve_cwd(inputs.get("cwd"))
    if not cwd.exists() or not cwd.is_dir():
        raise NotADirectoryError(f"cwd is not a directory: {cwd}")
    timeout = float(inputs.get("timeout", 600) or 600)
    max_output = max(1000, int(inputs.get("max_output_chars") or 12000))

    if bool(inputs.get("background", False)):
        return _start_background(command, shell, command_text, cwd, inputs)

    try:
        raise_if_interrupted()
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=shell,
            cwd=cwd,
            env=_merged_env(inputs),
            start_new_session=(os.name != "nt"),
        )
        deadline = time.monotonic() + timeout
        while True:
            try:
                stdout, stderr = proc.communicate(timeout=0.1)
                clipped_stdout, stdout_truncated = _clip_output(stdout, max_output)
                clipped_stderr, stderr_truncated = _clip_output(stderr, max_output)
                return {
                    "command": command_text,
                    "cwd": get_display_path(cwd),
                    "returncode": proc.returncode,
                    "success": proc.returncode == 0,
                    "stdout": clipped_stdout,
                    "stderr": clipped_stderr,
                    "stdout_truncated": stdout_truncated,
                    "stderr_truncated": stderr_truncated,
                    "stdout_tail": _tail_lines(stdout),
                    "stderr_tail": _tail_lines(stderr),
                }
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    _terminate_process(proc)
                    raise subprocess.TimeoutExpired(command_text, timeout)
                try:
                    raise_if_interrupted()
                except OperationInterrupted:
                    _terminate_process(proc)
                    raise OperationInterrupted("Command interrupted by /stop.")
    except subprocess.TimeoutExpired:
        return {
            "command": command_text,
            "cwd": get_display_path(cwd),
            "success": False,
            "error": f"Command timed out ({timeout:g} second limit)",
            "error_type": "timeout",
        }
    except OperationInterrupted:
        raise
    except Exception as exc:
        return {
            "command": command_text,
            "cwd": get_display_path(cwd),
            "success": False,
            "error": str(exc),
            "error_type": "exception",
        }


def _start_background(command, shell: bool, command_text: str, cwd: Path, inputs):
    stdout_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False)
    stderr_file = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False)
    stdout_path = stdout_file.name
    stderr_path = stderr_file.name
    try:
        proc = subprocess.Popen(
            command,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=shell,
            cwd=cwd,
            env=_merged_env(inputs),
            start_new_session=(os.name != "nt"),
        )
    finally:
        stdout_file.close()
        stderr_file.close()

    process_id = str(uuid.uuid4())
    _BACKGROUND_PROCS[process_id] = {
        "proc": proc,
        "command": command_text,
        "cwd": cwd,
        "stdout_path": stdout_path,
        "stderr_path": stderr_path,
        "started_at": time.time(),
    }
    return {
        "background": True,
        "process_id": process_id,
        "pid": proc.pid,
        "command": command_text,
        "cwd": get_display_path(cwd),
        "running": True,
    }


def _read_text_file(path: str, limit: int) -> tuple[str, bool]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    return _clip_output(text, limit)


def _background_snapshot(process_id: str, max_output: int = 12000) -> dict:
    item = _BACKGROUND_PROCS.get(process_id)
    if item is None:
        raise KeyError(f"Unknown background process_id: {process_id}")
    proc = item["proc"]
    stdout, stdout_truncated = _read_text_file(item["stdout_path"], max_output)
    stderr, stderr_truncated = _read_text_file(item["stderr_path"], max_output)
    return {
        "process_id": process_id,
        "pid": proc.pid,
        "command": item["command"],
        "cwd": get_display_path(item["cwd"]),
        "running": proc.poll() is None,
        "returncode": proc.poll(),
        "started_at": item["started_at"],
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "stdout_tail": _tail_lines(stdout),
        "stderr_tail": _tail_lines(stderr),
    }


def _list_background_commands(inputs):
    return {
        "count": len(_BACKGROUND_PROCS),
        "processes": [
            _background_snapshot(process_id, max_output=2000)
            for process_id in list(_BACKGROUND_PROCS)
        ],
    }


def _read_background_command(inputs):
    max_output = max(1000, int(inputs.get("max_output_chars") or 12000))
    return _background_snapshot(str(inputs["process_id"]), max_output=max_output)


def _stop_background_command(inputs):
    process_id = str(inputs["process_id"])
    item = _BACKGROUND_PROCS.get(process_id)
    if item is None:
        raise KeyError(f"Unknown background process_id: {process_id}")
    proc = item["proc"]
    was_running = proc.poll() is None
    if was_running:
        _terminate_process(proc)
    snapshot = _background_snapshot(process_id)
    snapshot["stopped"] = was_running
    return snapshot
