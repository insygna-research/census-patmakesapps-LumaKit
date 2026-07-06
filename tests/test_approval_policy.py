"""The security policy (S-4/S-6/D-2) — single source of truth in core/approval_policy.py."""

from core import auth
from core.approval_policy import (
    autonomous_tool_refusal,
    surface_tool_denial,
    tool_always_requires_approval,
)
from core.interface_context import set_interface


def test_exec_tools_always_require_approval():
    assert tool_always_requires_approval("execute_shell", {"command": "mv a b"})
    assert tool_always_requires_approval("execute_python", {"code": "print(1)"})
    assert tool_always_requires_approval("run_command", {"reason": "x", "command": "echo hi"})


def test_protected_write_tools_always_require_approval():
    for tool in ("delete_file", "git_add", "git_commit", "git_push"):
        assert tool_always_requires_approval(tool, {})


def test_read_tools_do_not_require_forced_approval():
    assert not tool_always_requires_approval("read_file", {"path": "x"})
    assert not tool_always_requires_approval("web_search", {"query": "x"})


def test_autonomous_tasks_refuse_protected_tools():
    assert autonomous_tool_refusal("git_push", {}) is not None
    assert autonomous_tool_refusal("delete_file", {"path": "x"}) is not None
    assert autonomous_tool_refusal("execute_shell", {"command": "rm -rf /"}) is not None
    assert autonomous_tool_refusal("execute_shell", {"command": "ls"}) is None


def test_telegram_role_scoping():
    auth.set_owner("111")
    try:
        auth.set_active_user("111")
        set_interface("telegram", "111")
        assert surface_tool_denial("execute_shell") is None  # owner unrestricted

        auth.set_active_user("222")
        set_interface("telegram", "222")
        assert surface_tool_denial("execute_shell") is not None
        assert surface_tool_denial("write_file") is not None
        assert surface_tool_denial("create_task") is not None
        assert surface_tool_denial("read_file") is None

        # web/CLI are single-user owner surfaces — unrestricted here
        set_interface("web", "web-user")
        assert surface_tool_denial("execute_shell") is None
    finally:
        set_interface(None, None)
        auth.set_active_user(None)
        auth.set_owner(None)
