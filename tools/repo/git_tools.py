from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.paths import get_display_path, get_repo_root


AUTH_ERRORS = (
    "authentication",
    "permission denied",
    "fatal: could not read",
    "logon failed",
    "403",
    "could not resolve host",
    "repository not found",
    "support for password authentication was removed",
)

CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def get_git_init_tool():
    return {
        "name": "git_init",
        "description": "Initialize a new git repository in the current directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "bare": {
                    "type": "boolean",
                    "description": "Create a bare repository (default: false)",
                }
            },
            "required": [],
        },
        "execute": _git_init,
    }


def get_git_status_tool():
    return {
        "name": "git_status",
        "description": (
            "Get parsed git status: branch, upstream, ahead/behind, staged, "
            "unstaged, untracked, conflicts, and cleanliness."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
        "execute": _git_status,
    }


def get_git_preflight_tool():
    return {
        "name": "git_preflight",
        "description": (
            "Summarize the repository state before commit or push: git root, "
            "branch, remotes, recent commits, dirty files, conflicts, and useful next actions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "recent_commits": {
                    "type": "integer",
                    "description": "Number of recent commits to include (default 5).",
                }
            },
        },
        "execute": _git_preflight,
    }


def get_git_add_tool():
    return {
        "name": "git_add",
        "description": "Stage files for commit. Prefer files as an array; use ['.'] to stage all changes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {
                    "description": "Files to stage. Accepts an array of paths or '.' for all.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why these files should be staged.",
                },
            },
            "required": ["files"],
        },
        "execute": _git_add,
    }


def get_git_commit_tool():
    return {
        "name": "git_commit",
        "description": (
            "Commit changes with a message. By default stages all tracked, untracked, "
            "modified, and deleted files before committing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Commit message"},
                "stage_all": {
                    "type": "boolean",
                    "description": "Stage all changes before committing (default true).",
                },
                "files": {
                    "description": "Optional array of files to stage instead of all changes.",
                },
                "allow_empty": {
                    "type": "boolean",
                    "description": "Allow an empty commit (default false).",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why this commit is being made.",
                },
            },
            "required": ["message", "reason"],
        },
        "execute": _git_commit,
    }


def get_git_push_tool():
    return {
        "name": "git_push",
        "description": (
            "Push commits to a remote. Handles missing upstreams, rejected pushes, "
            "and auth failures with structured diagnostics."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "remote": {"type": "string", "description": "Remote name (default origin)."},
                "branch": {"type": "string", "description": "Branch to push (default current branch)."},
                "set_upstream": {
                    "type": "boolean",
                    "description": "Set upstream when the branch has none (default true).",
                },
                "allow_interactive_auth": {
                    "type": "boolean",
                    "description": "Retry in the foreground if git requests interactive auth (default false).",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief explanation of why this push is needed.",
                },
            },
            "required": ["reason"],
        },
        "execute": _git_push,
    }


def get_git_pull_tool():
    return {
        "name": "git_pull",
        "description": (
            "Pull changes from a remote. Defaults to --ff-only to avoid surprise merge commits."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "remote": {"type": "string", "description": "Remote name (default origin)."},
                "branch": {"type": "string", "description": "Branch to pull (default current branch)."},
                "rebase": {"type": "boolean", "description": "Use git pull --rebase."},
                "ff_only": {
                    "type": "boolean",
                    "description": "Use git pull --ff-only (default true unless rebase=true).",
                },
            },
            "required": [],
        },
        "execute": _git_pull,
    }


def get_git_branch_tool():
    return {
        "name": "git_branch",
        "description": "List, create, switch, or delete git branches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create", "switch", "delete"],
                    "description": "Action to perform.",
                },
                "branch_name": {
                    "type": "string",
                    "description": "Branch name (required for create/switch/delete).",
                },
                "start_point": {
                    "type": "string",
                    "description": "Optional start point for create.",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force delete or force switch/create behavior when supported.",
                },
            },
            "required": ["action"],
        },
        "execute": _git_branch,
    }


def get_git_log_tool():
    return {
        "name": "git_log",
        "description": "View git commit history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "num_commits": {
                    "type": "number",
                    "description": "Number of commits to show (default 10).",
                }
            },
            "required": [],
        },
        "execute": _git_log,
    }


def _cmd_text(args: list[str]) -> str:
    return " ".join(args)


def _run_git(
    args: list[str],
    *,
    timeout: int = 30,
    interactive: bool = False,
) -> dict[str, Any]:
    command = ["git", *[str(arg) for arg in args]]
    try:
        if interactive:
            result = subprocess.run(
                command,
                cwd=get_repo_root(),
                stdin=sys.stdin,
                stdout=sys.stdout,
                stderr=sys.stderr,
                timeout=timeout,
                check=False,
            )
            return {
                "success": result.returncode == 0,
                "stdout": "",
                "stderr": "",
                "returncode": result.returncode,
                "command": _cmd_text(command),
            }

        result = subprocess.run(
            command,
            cwd=get_repo_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
            "command": _cmd_text(command),
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "returncode": None,
            "command": _cmd_text(command),
            "error_type": "timeout",
        }
    except Exception as exc:
        return {
            "success": False,
            "stdout": "",
            "stderr": str(exc),
            "returncode": None,
            "command": _cmd_text(command),
            "error_type": "exception",
        }


def _is_auth_error(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in AUTH_ERRORS)


def _classify_error(result: dict[str, Any]) -> dict[str, str]:
    combined = f"{result.get('stderr', '')}\n{result.get('stdout', '')}".lower()
    if result.get("error_type"):
        return {"error_type": str(result["error_type"]), "guidance": "Check the command result."}
    if _is_auth_error(combined):
        return {
            "error_type": "auth_required",
            "guidance": "Authenticate git for this remote, then retry the push or pull.",
        }
    if "nothing to commit" in combined or "no changes added to commit" in combined:
        return {
            "error_type": "nothing_to_commit",
            "guidance": "There are no staged changes to commit.",
        }
    if "please tell me who you are" in combined or "user.email" in combined:
        return {
            "error_type": "identity_required",
            "guidance": "Configure git user.name and user.email, then retry the commit.",
        }
    if "non-fast-forward" in combined or "fetch first" in combined or "rejected" in combined:
        return {
            "error_type": "non_fast_forward",
            "guidance": "Fetch or pull the remote branch, resolve any conflicts, then push again.",
        }
    if "no upstream branch" in combined or "has no upstream branch" in combined:
        return {
            "error_type": "no_upstream",
            "guidance": "Push with set_upstream=true or specify a remote and branch.",
        }
    if "merge conflict" in combined or "unmerged files" in combined or "needs merge" in combined:
        return {
            "error_type": "merge_conflict",
            "guidance": "Resolve merge conflicts before continuing.",
        }
    if "not a git repository" in combined:
        return {
            "error_type": "not_git_repository",
            "guidance": "Run this tool from inside a git repository or initialize one.",
        }
    if "src refspec" in combined:
        return {
            "error_type": "missing_branch",
            "guidance": "Check that the branch exists and has at least one commit.",
        }
    if "repository not found" in combined:
        return {
            "error_type": "remote_not_found",
            "guidance": "Check the remote URL and repository permissions.",
        }
    return {"error_type": "git_error", "guidance": "Inspect stdout/stderr and retry with corrected inputs."}


def _normalize_files(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if text in {".", "-A", "--all"}:
        return ["."]
    if "\n" in text:
        return [part.strip() for part in text.splitlines() if part.strip()]
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def _parse_branch_line(line: str) -> dict[str, Any]:
    text = line[3:].strip() if line.startswith("## ") else line.strip()
    branch = {
        "name": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
        "detached": False,
        "raw": text,
    }
    if text.startswith("HEAD"):
        branch["detached"] = True
        return branch

    if "..." in text:
        name, rest = text.split("...", 1)
        branch["name"] = name.strip()
        upstream = rest.split(" ", 1)[0].strip()
        branch["upstream"] = upstream or None
    else:
        branch["name"] = text.split(" ", 1)[0].strip() or None

    ahead = re.search(r"ahead (\d+)", text)
    behind = re.search(r"behind (\d+)", text)
    if ahead:
        branch["ahead"] = int(ahead.group(1))
    if behind:
        branch["behind"] = int(behind.group(1))
    return branch


def _parse_status(output: str) -> dict[str, Any]:
    branch = {
        "name": None,
        "upstream": None,
        "ahead": 0,
        "behind": 0,
        "detached": False,
        "raw": "",
    }
    entries = []
    for line in output.splitlines():
        if not line:
            continue
        if line.startswith("## "):
            branch = _parse_branch_line(line)
            continue
        if line.startswith("?? "):
            entries.append({
                "path": line[3:],
                "index_status": "?",
                "worktree_status": "?",
                "category": "untracked",
                "staged": False,
                "unstaged": False,
                "conflict": False,
            })
            continue
        if len(line) < 4:
            continue
        index_status = line[0]
        worktree_status = line[1]
        path_text = line[3:]
        old_path = None
        path = path_text
        if " -> " in path_text:
            old_path, path = path_text.split(" -> ", 1)
        code = f"{index_status}{worktree_status}"
        conflict = code in CONFLICT_CODES
        staged = index_status not in {" ", "?"}
        unstaged = worktree_status not in {" ", "?"}
        category = "conflict" if conflict else "changed"
        entries.append({
            "path": path,
            "old_path": old_path,
            "index_status": index_status,
            "worktree_status": worktree_status,
            "category": category,
            "staged": staged,
            "unstaged": unstaged,
            "conflict": conflict,
        })
    return {
        "branch": branch,
        "entries": entries,
        "staged": [entry for entry in entries if entry["staged"] and not entry["conflict"]],
        "unstaged": [entry for entry in entries if entry["unstaged"] and not entry["conflict"]],
        "untracked": [entry for entry in entries if entry["category"] == "untracked"],
        "conflicts": [entry for entry in entries if entry["conflict"]],
        "clean": not entries,
    }


def _status_data() -> dict[str, Any]:
    inside = _run_git(["rev-parse", "--is-inside-work-tree"])
    if not inside["success"]:
        return {
            "success": False,
            **_classify_error(inside),
            "stderr": inside.get("stderr", ""),
            "command": inside.get("command"),
        }

    top = _run_git(["rev-parse", "--show-toplevel"])
    status = _run_git(["status", "--short", "--branch", "--untracked-files=all"])
    if not status["success"]:
        return {
            "success": False,
            **_classify_error(status),
            "stderr": status.get("stderr", ""),
            "command": status.get("command"),
        }

    parsed = _parse_status(status["stdout"])
    parsed.update({
        "success": True,
        "git_root": top["stdout"] if top["success"] else str(get_repo_root()),
        "cwd": str(get_repo_root()),
        "raw": status["stdout"],
    })
    return parsed


def _remote_data() -> list[dict[str, str]]:
    result = _run_git(["remote", "-v"])
    if not result["success"] or not result["stdout"]:
        return []
    remotes = []
    seen = set()
    for line in result["stdout"].splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        key = (parts[0], parts[1], parts[2].strip("()"))
        if key in seen:
            continue
        seen.add(key)
        remotes.append({"name": parts[0], "url": parts[1], "type": parts[2].strip("()")})
    return remotes


def _current_branch(status: dict[str, Any] | None = None) -> str | None:
    if status and status.get("branch", {}).get("name"):
        return status["branch"]["name"]
    result = _run_git(["branch", "--show-current"])
    return result["stdout"] if result["success"] and result["stdout"] else None


def _git_init(inputs):
    args = ["init", "--bare"] if inputs.get("bare", False) else ["init"]
    result = _run_git(args)
    if not result["success"]:
        return {"initialized": False, **_classify_error(result), **result}
    return {
        "initialized": True,
        "bare": bool(inputs.get("bare", False)),
        "output": result["stdout"],
        "command": result["command"],
    }


def _git_status(inputs):
    status = _status_data()
    if not status.get("success"):
        return status
    status["remotes"] = _remote_data()
    return status


def _git_preflight(inputs):
    status = _status_data()
    if not status.get("success"):
        return status
    recent_count = int(inputs.get("recent_commits", 5) or 5)
    log = _run_git(["log", "--oneline", "--decorate", "-n", str(recent_count)])
    actions = []
    if status["conflicts"]:
        actions.append("Resolve merge conflicts before editing, committing, pulling, or pushing.")
    if status["staged"]:
        actions.append("A commit can be created from staged changes.")
    if status["unstaged"] or status["untracked"]:
        actions.append("Stage changes before committing, or use git_commit with stage_all=true.")
    branch = status["branch"]
    if branch.get("ahead", 0) > 0:
        actions.append("Local branch has commits ready to push.")
    if branch.get("behind", 0) > 0:
        actions.append("Remote branch has commits to pull before pushing.")
    if not actions:
        actions.append("Working tree is clean.")

    return {
        **status,
        "remotes": _remote_data(),
        "recent_commits": log["stdout"].splitlines() if log["success"] and log["stdout"] else [],
        "recommended_next_actions": actions,
    }


def _git_add(inputs):
    files = _normalize_files(inputs.get("files"))
    if not files:
        return {"added": False, "error_type": "invalid_input", "error": "No files were provided."}

    args = ["add", "-A"] if files == ["."] else ["add", "--", *files]
    result = _run_git(args)
    if not result["success"]:
        return {"added": False, **_classify_error(result), **result}
    return {
        "added": True,
        "files": files,
        "command": result["command"],
        "status": _status_data(),
    }


def _git_commit(inputs):
    message = str(inputs.get("message", "")).strip()
    if not message:
        return {
            "committed": False,
            "error_type": "invalid_input",
            "error": "Commit message must not be empty.",
        }

    status_before = _status_data()
    if not status_before.get("success"):
        return {"committed": False, **status_before}
    if status_before["conflicts"]:
        return {
            "committed": False,
            "error_type": "merge_conflict",
            "guidance": "Resolve conflicts before committing.",
            "status": status_before,
        }

    files = _normalize_files(inputs.get("files"))
    stage_all = bool(inputs.get("stage_all", True)) if not files else False
    if stage_all:
        add_result = _run_git(["add", "-A"])
        if not add_result["success"]:
            return {"committed": False, **_classify_error(add_result), **add_result}
    elif files:
        add_result = _run_git(["add", "--", *files])
        if not add_result["success"]:
            return {"committed": False, **_classify_error(add_result), **add_result}

    status_after_add = _status_data()
    if not status_after_add.get("success"):
        return {"committed": False, **status_after_add}
    if not status_after_add["staged"] and not bool(inputs.get("allow_empty", False)):
        return {
            "committed": False,
            "nothing_to_commit": True,
            "error_type": "nothing_to_commit",
            "guidance": "No staged changes were available to commit.",
            "status": status_after_add,
        }

    args = ["commit", "-m", message]
    if bool(inputs.get("allow_empty", False)):
        args.insert(1, "--allow-empty")
    commit = _run_git(args, timeout=60)
    if not commit["success"]:
        return {
            "committed": False,
            **_classify_error(commit),
            **commit,
            "status": _status_data(),
        }

    sha = _run_git(["rev-parse", "--short", "HEAD"])
    return {
        "committed": True,
        "message": message,
        "commit": sha["stdout"] if sha["success"] else None,
        "output": commit["stdout"],
        "command": commit["command"],
        "status": _status_data(),
    }


def _git_push(inputs):
    status = _status_data()
    if not status.get("success"):
        return {"pushed": False, **status}
    if status["conflicts"]:
        return {
            "pushed": False,
            "error_type": "merge_conflict",
            "guidance": "Resolve conflicts before pushing.",
            "status": status,
        }

    remote = str(inputs.get("remote") or "origin").strip()
    branch = str(inputs.get("branch") or _current_branch(status) or "").strip()
    if not branch:
        return {
            "pushed": False,
            "error_type": "detached_head",
            "guidance": "Create or switch to a branch before pushing.",
            "status": status,
        }

    remote_check = _run_git(["remote", "get-url", remote])
    if not remote_check["success"]:
        return {
            "pushed": False,
            "error_type": "remote_missing",
            "guidance": f"Remote '{remote}' is not configured.",
            **remote_check,
        }

    set_upstream = bool(inputs.get("set_upstream", True))
    has_upstream = bool(status.get("branch", {}).get("upstream"))
    if set_upstream and not has_upstream:
        args = ["push", "-u", remote, branch]
    elif inputs.get("branch") or inputs.get("remote"):
        args = ["push", remote, branch]
    else:
        args = ["push"]

    result = _run_git(args, timeout=120)
    if not result["success"] and _is_auth_error(f"{result.get('stderr', '')}\n{result.get('stdout', '')}"):
        if bool(inputs.get("allow_interactive_auth", False)):
            result = _run_git(args, timeout=180, interactive=True)
        else:
            return {
                "pushed": False,
                **_classify_error(result),
                **result,
                "remote": remote,
                "branch": branch,
            }

    if not result["success"]:
        return {
            "pushed": False,
            **_classify_error(result),
            **result,
            "remote": remote,
            "branch": branch,
            "status": _status_data(),
        }

    return {
        "pushed": True,
        "remote": remote,
        "branch": branch,
        "upstream_set": set_upstream and not has_upstream,
        "output": result["stdout"],
        "command": result["command"],
        "status": _status_data(),
    }


def _git_pull(inputs):
    status = _status_data()
    if not status.get("success"):
        return {"pulled": False, **status}
    if status["conflicts"]:
        return {
            "pulled": False,
            "error_type": "merge_conflict",
            "guidance": "Resolve conflicts before pulling.",
            "status": status,
        }

    remote = str(inputs.get("remote") or "origin").strip()
    branch = str(inputs.get("branch") or _current_branch(status) or "").strip()
    if not branch:
        return {
            "pulled": False,
            "error_type": "detached_head",
            "guidance": "Switch to a branch before pulling.",
            "status": status,
        }

    rebase = bool(inputs.get("rebase", False))
    ff_only = bool(inputs.get("ff_only", not rebase))
    args = ["pull"]
    if rebase:
        args.append("--rebase")
    elif ff_only:
        args.append("--ff-only")
    args.extend([remote, branch])

    result = _run_git(args, timeout=120)
    if not result["success"]:
        return {
            "pulled": False,
            **_classify_error(result),
            **result,
            "remote": remote,
            "branch": branch,
            "status": _status_data(),
        }
    return {
        "pulled": True,
        "remote": remote,
        "branch": branch,
        "output": result["stdout"],
        "command": result["command"],
        "status": _status_data(),
    }


def _git_branch(inputs):
    action = inputs.get("action", "list")
    branch_name = str(inputs.get("branch_name") or "").strip()
    force = bool(inputs.get("force", False))

    if action == "list":
        result = _run_git(["branch", "-a", "--verbose"])
    elif action == "create":
        if not branch_name:
            return {"success": False, "error_type": "invalid_input", "error": "branch_name is required."}
        args = ["branch"]
        if force:
            args.append("-f")
        args.append(branch_name)
        if inputs.get("start_point"):
            args.append(str(inputs["start_point"]))
        result = _run_git(args)
    elif action == "switch":
        if not branch_name:
            return {"success": False, "error_type": "invalid_input", "error": "branch_name is required."}
        args = ["switch"]
        if force:
            args.append("--force")
        args.append(branch_name)
        result = _run_git(args)
    elif action == "delete":
        if not branch_name:
            return {"success": False, "error_type": "invalid_input", "error": "branch_name is required."}
        result = _run_git(["branch", "-D" if force else "-d", branch_name])
    else:
        return {"success": False, "error_type": "invalid_input", "error": f"Unknown action: {action}"}

    if not result["success"]:
        return {
            "success": False,
            "action": action,
            "branch": branch_name or None,
            **_classify_error(result),
            **result,
        }

    return {
        "success": True,
        "action": action,
        "branch": branch_name or None,
        "output": result["stdout"],
        "command": result["command"],
        "status": _status_data() if action != "list" else None,
    }


def _git_log(inputs):
    num_commits = int(inputs.get("num_commits", 10) or 10)
    num_commits = max(1, min(num_commits, 100))
    result = _run_git(["log", "--oneline", "--decorate", "-n", str(num_commits)])
    if not result["success"]:
        return {"success": False, **_classify_error(result), **result}
    return {
        "success": True,
        "commits": result["stdout"].splitlines() if result["stdout"] else [],
        "num_commits": num_commits,
        "command": result["command"],
    }
