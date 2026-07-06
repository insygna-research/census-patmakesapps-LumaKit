"""S-2: filesystem sandbox in core.paths."""

from pathlib import Path

import pytest

from core.paths import ensure_tool_path_allowed, resolve_repo_path


def test_in_workspace_path_allowed(workspace):
    target = workspace / "hello.txt"
    target.write_text("hi", encoding="utf-8")
    resolved = resolve_repo_path("hello.txt", kind="file")
    assert resolved == target.resolve()


def test_escape_outside_workspace_denied(workspace):
    outside = workspace.parent / "escape.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError):
        resolve_repo_path(str(outside), kind="file")


def test_traversal_denied(workspace):
    (workspace / "sub").mkdir()
    outside = workspace.parent / "up.txt"
    outside.write_text("secret", encoding="utf-8")
    with pytest.raises(PermissionError):
        resolve_repo_path("../up.txt", must_exist=False)


def test_env_denied_even_inside_workspace(workspace):
    (workspace / ".env").write_text("KEY=1", encoding="utf-8")
    with pytest.raises(PermissionError):
        resolve_repo_path(".env", kind="file")


def test_lumakit_data_dir_denied(workspace):
    token_path = Path.home() / ".lumakit" / "web_session_token"
    with pytest.raises(PermissionError):
        ensure_tool_path_allowed(token_path)
    with pytest.raises(PermissionError):
        ensure_tool_path_allowed(Path.home() / ".lumakit" / "config.env")


def test_git_config_denied(workspace):
    git_dir = workspace / ".git"
    git_dir.mkdir()
    cfg = git_dir / "config"
    cfg.write_text("[core]", encoding="utf-8")
    with pytest.raises(PermissionError):
        ensure_tool_path_allowed(cfg)


def test_allow_paths_opt_in(workspace, monkeypatch, tmp_path):
    import os

    extra = tmp_path / "extra"
    extra.mkdir()
    target = extra / "ok.txt"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(PermissionError):
        ensure_tool_path_allowed(target)
    monkeypatch.setenv("LUMAKIT_ALLOW_PATHS", str(extra))
    assert ensure_tool_path_allowed(target) == target
