"""§6.3: cross-surface approval round-trip for autonomous tasks."""

import pytest

import core.task_store as ts
from core import task_approvals


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "DB_PATH", tmp_path / "tasks.db")
    return ts


def _task_with_session(store):
    task_id = store.create_task(title="deploy", goal="ship it", owner_chat_id="owner")
    store.save_session(task_id, [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "go"},
    ])
    return store.get_task(task_id)


def test_request_blocks_and_records(store):
    task = _task_with_session(store)
    record = task_approvals.request_approval(task, "execute_shell", {"command": "rm -rf build"})
    assert record["summary"] == "rm -rf build"
    fresh = store.get_task(task["id"])
    assert fresh["status"] == "blocked"
    assert task_approvals.pending_approval(fresh)["tool"] == "execute_shell"
    assert any(e["type"] == "approval_requested" for e in fresh["history"])


def test_approve_grants_once_and_resumes(store):
    task = _task_with_session(store)
    task_approvals.request_approval(task, "execute_shell", {"command": "rm -rf build"})

    ok, msg = task_approvals.approve(task["id"])
    assert ok, msg
    fresh = store.get_task(task["id"])
    assert fresh["status"] == "active"
    assert task_approvals.pending_approval(fresh) is None
    # resume guidance injected into the thread
    assert "APPROVED" in fresh["messages"][-1]["content"]

    # grant matches the exact action, once
    assert task_approvals.consume_grant(fresh, "execute_shell", {"command": "rm -rf build"})
    fresh = store.get_task(task["id"])
    assert not task_approvals.consume_grant(fresh, "execute_shell", {"command": "rm -rf build"})


def test_grant_does_not_match_different_command(store):
    task = _task_with_session(store)
    task_approvals.request_approval(task, "execute_shell", {"command": "rm -rf build"})
    task_approvals.approve(task["id"])
    fresh = store.get_task(task["id"])
    assert not task_approvals.consume_grant(fresh, "execute_shell", {"command": "rm -rf /"})
    assert not task_approvals.consume_grant(fresh, "git_push", {})


def test_deny_resumes_without_grant(store):
    task = _task_with_session(store)
    task_approvals.request_approval(task, "git_push", {})
    ok, _ = task_approvals.deny(task["id"])
    assert ok
    fresh = store.get_task(task["id"])
    assert fresh["status"] == "active"
    assert "DENIED" in fresh["messages"][-1]["content"]
    assert not task_approvals.consume_grant(fresh, "git_push", {})


def test_approve_without_pending_fails(store):
    task = _task_with_session(store)
    ok, msg = task_approvals.approve(task["id"])
    assert not ok and "no pending approval" in msg
