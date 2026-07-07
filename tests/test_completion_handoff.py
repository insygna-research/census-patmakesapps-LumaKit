"""§6.3 completion handoff: files-changed artifact + shared changed-path logic."""

import pytest

import core.task_store as ts
from core.task_runner import TaskRunner
from tools.code_intel.code_index import changed_paths_from_tool


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "DB_PATH", tmp_path / "tasks.db")
    return ts


def _runner(notifications=None):
    sink = notifications if notifications is not None else []
    return TaskRunner(notify=lambda msg, cid: sink.append(msg))


# --- changed_paths_from_tool (single source of truth, D-2) ---------------

def test_changed_paths_simple_tools():
    ok = {"success": True}
    assert changed_paths_from_tool("write_file", {"path": "a.py"}, ok) == ["a.py"]
    assert changed_paths_from_tool("edit_file", {"path": "b.py"}, ok) == ["b.py"]
    assert changed_paths_from_tool("delete_file", {"path": "c.py"}, ok) == ["c.py"]
    assert changed_paths_from_tool("read_file", {"path": "d.py"}, ok) == []


def test_changed_paths_failure_returns_nothing():
    assert changed_paths_from_tool("write_file", {"path": "a.py"}, {"success": False}) == []


def test_changed_paths_apply_patch_and_move():
    patch_result = {"success": True, "data": {"changed_files": [
        {"path": "new.py", "old_path": "old.py"},
        {"path": "same.py"},
    ]}}
    assert changed_paths_from_tool("apply_patch", {}, patch_result) == [
        "new.py", "old.py", "same.py",
    ]
    move_result = {"success": True, "data": {"source_path": "src.py", "destination_path": "dst.py"}}
    assert changed_paths_from_tool("move_path", {}, move_result) == ["src.py", "dst.py"]


# --- runner-side accumulation --------------------------------------------

def test_record_changed_files_accumulates_distinct(store):
    task_id = store.create_task(title="t", goal="g")
    runner = _runner()
    ok = {"success": True}
    runner._record_changed_files(task_id, "write_file", {"path": "a.py"}, ok)
    runner._record_changed_files(task_id, "edit_file", {"path": "a.py"}, ok)  # dup
    runner._record_changed_files(task_id, "write_file", {"path": "b.py"}, ok)
    runner._record_changed_files(task_id, "read_file", {"path": "c.py"}, ok)  # not mutating
    files = store.get_task(task_id)["constraints"]["_files_changed"]
    assert files == ["a.py", "b.py"]


def test_record_changed_files_caps_with_overflow(store, monkeypatch):
    monkeypatch.setattr(TaskRunner, "CHANGED_FILES_CAP", 3)
    task_id = store.create_task(title="t", goal="g")
    runner = _runner()
    for i in range(5):
        runner._record_changed_files(task_id, "write_file", {"path": f"f{i}.py"}, {"success": True})
    constraints = store.get_task(task_id)["constraints"]
    assert len(constraints["_files_changed"]) == 3
    assert constraints["_files_changed_overflow"] == 2  # f3 and f4 overflowed
    note = TaskRunner._files_changed_note(constraints)
    assert note.startswith("Files changed (5)")  # total reflects reality


def test_files_changed_note_formatting():
    assert TaskRunner._files_changed_note({}) == ""
    note = TaskRunner._files_changed_note({"_files_changed": [f"f{i}.py" for i in range(10)]})
    assert note.startswith("Files changed (10):")
    assert "(+2 more)" in note


def test_finalize_includes_files_in_notification_and_history(store):
    notifications = []
    task_id = store.create_task(title="ship it", goal="g", owner_chat_id="owner")
    store.save_session(task_id, [{"role": "system", "content": "s"}])
    runner = _runner(notifications)
    runner._record_changed_files(task_id, "write_file", {"path": "index.html"}, {"success": True})

    task = store.get_task(task_id)
    runner._finalize(task, "done", "All done.")

    final = store.get_task(task_id)
    assert final["status"] == "done"
    assert any("Files changed (1): index.html" in n for n in notifications)
    assert any(
        e["type"] == "files_changed" and "index.html" in e.get("detail", "")
        for e in final["history"]
    )
