"""Persistent store for autonomous tasks.

Tasks live in the same memory/ directory as memories, in a separate
tasks.db file so they don't collide with the memory schema.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from typing import Callable

from core.paths import get_data_dir

DB_PATH = get_data_dir() / "memory" / "tasks.db"

# Soft cap on per-task history length. Older entries are dropped on append
# once the list grows past this size — protects long-running tasks from
# unbounded growth in the SQLite blob.
HISTORY_SOFT_CAP = 400

# ---------------------------------------------------------------------------
# Event broadcaster — task_runner mutations and explicit user actions emit
# events that the web layer subscribes to for live updates.
# ---------------------------------------------------------------------------

_listeners: list[Callable[[dict], None]] = []
_listeners_lock = threading.RLock()


def subscribe(cb: Callable[[dict], None]) -> None:
    with _listeners_lock:
        _listeners.append(cb)


def unsubscribe(cb: Callable[[dict], None]) -> None:
    with _listeners_lock:
        try:
            _listeners.remove(cb)
        except ValueError:
            pass


def _emit(event: dict) -> None:
    with _listeners_lock:
        callbacks = list(_listeners)
    for cb in callbacks:
        try:
            cb(event)
        except Exception:
            pass


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            goal        TEXT NOT NULL,
            constraints TEXT NOT NULL DEFAULT '{}',
            status      TEXT NOT NULL DEFAULT 'planning',
            plan        TEXT NOT NULL DEFAULT '[]',
            current_step INTEGER NOT NULL DEFAULT 0,
            history     TEXT NOT NULL DEFAULT '[]',
            owner_chat_id TEXT,
            created_at  TEXT NOT NULL,
            due_at      TEXT,
            next_run_at TEXT,
            workspace_path TEXT,
            result      TEXT
        )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "workspace_path" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN workspace_path TEXT")
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def create_task(
    title: str,
    goal: str,
    constraints: dict | None = None,
    owner_chat_id: str | None = None,
    due_at: str | None = None,
    start_at: str | None = None,
    workspace_path: str | None = None,
) -> int:
    """Insert a new task and return its id.

    start_at is when planning should kick off (defaults to now). Use this for
    tasks the user wants to begin at a specific future time — it's stored in
    next_run_at so the runner will skip the task until that moment.
    """
    conn = _connect()
    conn.execute(
        """INSERT INTO tasks
           (title, goal, constraints, status, plan, current_step,
            history, owner_chat_id, created_at, due_at, next_run_at, workspace_path)
           VALUES (?, ?, ?, 'planning', '[]', 0, '[]', ?, ?, ?, ?, ?)""",
        (
            title,
            goal,
            json.dumps(constraints or {}),
            owner_chat_id,
            datetime.now().isoformat(),
            due_at,
            start_at or datetime.now().isoformat(),
            workspace_path,
        ),
    )
    conn.commit()
    task_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    _emit({"type": "task_created", "task_id": task_id})
    return task_id


def set_plan(task_id: int, plan: list, next_run_at: str | None = None) -> None:
    """Store the generated plan and switch status to active."""
    conn = _connect()
    conn.execute(
        "UPDATE tasks SET plan=?, status='active', current_step=0, next_run_at=? WHERE id=?",
        (json.dumps(plan), next_run_at or datetime.now().isoformat(), task_id),
    )
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "status": "active"})


def append_history(task_id: int, entry: dict) -> None:
    """Append one entry to the task's history log.

    Caps the stored history at HISTORY_SOFT_CAP entries; older entries are
    dropped to keep the SQLite blob from growing without bound.
    """
    conn = _connect()
    row = conn.execute("SELECT history FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return
    history = json.loads(row["history"])
    entry_with_ts = {**entry, "timestamp": datetime.now().isoformat()}
    history.append(entry_with_ts)
    if len(history) > HISTORY_SOFT_CAP:
        history = history[-HISTORY_SOFT_CAP:]
    conn.execute("UPDATE tasks SET history=? WHERE id=?", (json.dumps(history), task_id))
    conn.commit()
    conn.close()
    _emit({"type": "history_appended", "task_id": task_id, "entry": entry_with_ts})


def advance_step(task_id: int, next_run_at: str) -> None:
    """Move to the next step and schedule its run time."""
    conn = _connect()
    conn.execute(
        "UPDATE tasks SET current_step = current_step + 1, next_run_at=? WHERE id=?",
        (next_run_at, task_id),
    )
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "field": "current_step"})


def update_task(task_id: int, **kwargs) -> None:
    """Generic field update. Caller passes column=value pairs."""
    if not kwargs:
        return
    cols = ", ".join(f"{k}=?" for k in kwargs)
    conn = _connect()
    conn.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*kwargs.values(), task_id))
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "fields": list(kwargs.keys())})


def complete_task(task_id: int, result: str) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE tasks SET status='done', result=? WHERE id=?",
        (result, task_id),
    )
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "status": "done"})


def fail_task(task_id: int, reason: str) -> None:
    conn = _connect()
    conn.execute(
        "UPDATE tasks SET status='failed', result=? WHERE id=?",
        (reason, task_id),
    )
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "status": "failed"})


def pause_task(task_id: int) -> bool:
    """Mark an active task as paused so the runner skips it."""
    conn = _connect()
    cursor = conn.execute(
        "UPDATE tasks SET status='paused' WHERE id=? AND status IN ('planning', 'active')",
        (task_id,),
    )
    conn.commit()
    conn.close()
    if cursor.rowcount > 0:
        _emit({"type": "task_updated", "task_id": task_id, "status": "paused"})
        return True
    return False


def resume_task(task_id: int) -> bool:
    """Resume a paused or blocked task. next_run_at is set to now so the runner
    picks it up on the next tick. Status reverts to 'planning' if no plan
    exists yet, otherwise 'active'.
    """
    conn = _connect()
    row = conn.execute(
        "SELECT plan, status FROM tasks WHERE id=?", (task_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    if row["status"] not in ("paused", "blocked"):
        conn.close()
        return False
    plan = json.loads(row["plan"] or "[]")
    new_status = "active" if plan else "planning"
    conn.execute(
        "UPDATE tasks SET status=?, next_run_at=? WHERE id=?",
        (new_status, datetime.now().isoformat(), task_id),
    )
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "status": new_status})
    return True


def restart_task(task_id: int) -> bool:
    """Restart a cancelled or failed task. Resets plan/current_step/result and
    flips status back to 'planning' so the runner regenerates a plan on the
    next tick. History is preserved as an audit trail.
    """
    conn = _connect()
    row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return False
    if row["status"] not in ("cancelled", "failed", "done"):
        conn.close()
        return False
    conn.execute(
        """UPDATE tasks
           SET status='planning', plan='[]', current_step=0,
               result=NULL, next_run_at=?
           WHERE id=?""",
        (datetime.now().isoformat(), task_id),
    )
    conn.commit()
    conn.close()
    _emit({"type": "task_updated", "task_id": task_id, "status": "planning"})
    # Audit trail so users see this attempt didn't just appear from nowhere.
    append_history(task_id, {"type": "restarted"})
    return True


def cancel_task(task_id: int) -> bool:
    """Mark a task as cancelled. Stops any further runner work but keeps the
    record so the user can still view its history.
    """
    conn = _connect()
    cursor = conn.execute(
        "UPDATE tasks SET status='cancelled' WHERE id=? AND status NOT IN ('done', 'failed', 'cancelled')",
        (task_id,),
    )
    conn.commit()
    conn.close()
    if cursor.rowcount > 0:
        _emit({"type": "task_updated", "task_id": task_id, "status": "cancelled"})
        return True
    return False


def delete_task(task_id: int) -> bool:
    """Permanently delete a task. Returns False if it wasn't found."""
    conn = _connect()
    cursor = conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    if cursor.rowcount > 0:
        _emit({"type": "task_deleted", "task_id": task_id})
        return True
    return False


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def get_task(task_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return _deserialize(dict(row))


def get_tasks_by_owner(chat_id: str, limit: int = 20) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE owner_chat_id=? ORDER BY created_at DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    conn.close()
    return [_deserialize(dict(r)) for r in rows]


def get_all_tasks(limit: int = 50) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [_deserialize(dict(r)) for r in rows]


def get_due_tasks() -> list[dict]:
    """Return tasks that are ready for the runner to process.

    Includes:
    - Tasks in 'planning' state (need plan generated, next_run_at <= now)
    - Tasks in 'active' state where next_run_at <= now
    - Tasks in any non-terminal state where due_at has passed (for final report)
    """
    now = datetime.now().isoformat()
    conn = _connect()
    rows = conn.execute(
        """SELECT * FROM tasks
           WHERE status IN ('planning', 'active')
             AND next_run_at <= ?
           ORDER BY next_run_at ASC""",
        (now,),
    ).fetchall()
    conn.close()
    return [_deserialize(dict(r)) for r in rows]


def get_overdue_tasks() -> list[dict]:
    """Return tasks past their due_at that haven't been finalized."""
    now = datetime.now().isoformat()
    conn = _connect()
    rows = conn.execute(
        """SELECT * FROM tasks
           WHERE status NOT IN ('done', 'failed', 'cancelled')
             AND due_at IS NOT NULL
             AND due_at <= ?""",
        (now,),
    ).fetchall()
    conn.close()
    return [_deserialize(dict(r)) for r in rows]


def _deserialize(row: dict) -> dict:
    """Parse JSON fields back to Python objects."""
    for field in ("constraints", "plan", "history"):
        if isinstance(row.get(field), str):
            try:
                row[field] = json.loads(row[field])
            except (json.JSONDecodeError, TypeError):
                row[field] = {} if field == "constraints" else []
    return row
