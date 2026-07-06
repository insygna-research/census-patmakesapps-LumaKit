"""R-1/R-5: task store durability — append-only history, WAL, caps."""

import json
import sqlite3

import pytest

import core.task_store as ts


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "DB_PATH", tmp_path / "nested" / "tasks.db")
    return ts


def test_history_append_only_and_capped(store):
    task_id = store.create_task(title="t", goal="g", owner_chat_id="u")
    for i in range(store.HISTORY_SOFT_CAP + 25):
        store.append_history(task_id, {"type": "activity", "n": i})
    task = store.get_task(task_id)
    assert len(task["history"]) == store.HISTORY_SOFT_CAP
    assert task["history"][-1]["n"] == store.HISTORY_SOFT_CAP + 24
    # legacy blob column stays empty
    conn = sqlite3.connect(str(store.DB_PATH))
    assert conn.execute("SELECT history FROM tasks WHERE id=?", (task_id,)).fetchone()[0] == "[]"
    conn.close()


def test_legacy_blob_migration(store):
    store.create_task(title="seed", goal="g")  # ensures schema exists
    conn = sqlite3.connect(str(store.DB_PATH))
    conn.execute(
        "INSERT INTO tasks (title, goal, created_at, history) VALUES ('legacy','g','2026-01-01',?)",
        (json.dumps([{"type": "old", "n": i} for i in range(3)]),),
    )
    legacy_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    migrated = store.get_task(legacy_id)  # reconnect triggers migration
    assert [e["type"] for e in migrated["history"]] == ["old"] * 3


def test_delete_cleans_history(store):
    task_id = store.create_task(title="del", goal="g")
    store.append_history(task_id, {"type": "x"})
    assert store.delete_task(task_id)
    conn = sqlite3.connect(str(store.DB_PATH))
    left = conn.execute("SELECT COUNT(*) FROM task_history WHERE task_id=?", (task_id,)).fetchone()[0]
    conn.close()
    assert left == 0


def test_wal_mode_enabled(store):
    store.create_task(title="w", goal="g")
    conn = sqlite3.connect(str(store.DB_PATH))
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
