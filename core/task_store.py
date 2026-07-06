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
    from core.db import connect as db_connect
    conn = db_connect(DB_PATH)
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
            result      TEXT,
            messages    TEXT NOT NULL DEFAULT '[]'
        )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "workspace_path" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN workspace_path TEXT")
    # Persistent agent conversation thread (the continuous task session). Lets a
    # long-running task keep full context across rounds and survive restarts.
    if "messages" not in columns:
        conn.execute("ALTER TABLE tasks ADD COLUMN messages TEXT NOT NULL DEFAULT '[]'")
    # Append-only history (R-5): one row per entry instead of rewriting a JSON
    # blob per append, so per-round write cost stays constant on long tasks.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            entry TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_history_task ON task_history(task_id, id)"
    )
    # One-time migration of legacy blob histories into the table. task_store is
    # the sole owner of tasks.db's user_version.
    if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
        for row in conn.execute("SELECT id, history FROM tasks WHERE history != '[]'").fetchall():
            try:
                entries = json.loads(row["history"])
            except (json.JSONDecodeError, TypeError):
                entries = []
            for entry in entries:
                conn.execute(
                    "INSERT INTO task_history (task_id, entry) VALUES (?, ?)",
                    (row["id"], json.dumps(entry, default=str)),
                )
        conn.execute("UPDATE tasks SET history='[]'")
        conn.execute("PRAGMA user_version = 1")
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
    """Append one entry to the task's history log (append-only table, R-5).

    Keeps at most HISTORY_SOFT_CAP entries per task; older rows are pruned so
    multi-day tasks don't grow without bound.
    """
    conn = _connect()
    exists = conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not exists:
        conn.close()
        return
    entry_with_ts = {**entry, "timestamp": datetime.now().isoformat()}
    conn.execute(
        "INSERT INTO task_history (task_id, entry) VALUES (?, ?)",
        (task_id, json.dumps(entry_with_ts, default=str)),
    )
    conn.execute(
        """DELETE FROM task_history
           WHERE task_id = ?
             AND id NOT IN (
                 SELECT id FROM task_history WHERE task_id = ?
                 ORDER BY id DESC LIMIT ?
             )""",
        (task_id, task_id, HISTORY_SOFT_CAP),
    )
    conn.commit()
    conn.close()
    _emit({"type": "history_appended", "task_id": task_id, "entry": entry_with_ts})


def _load_histories(conn, task_ids: list[int]) -> dict[int, list]:
    """Fetch histories for a set of tasks in one query."""
    if not task_ids:
        return {}
    placeholders = ",".join("?" for _ in task_ids)
    rows = conn.execute(
        f"SELECT task_id, entry FROM task_history WHERE task_id IN ({placeholders}) ORDER BY id",
        task_ids,
    ).fetchall()
    histories: dict[int, list] = {tid: [] for tid in task_ids}
    for row in rows:
        try:
            histories[row["task_id"]].append(json.loads(row["entry"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return histories


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
    conn.execute("DELETE FROM task_history WHERE task_id=?", (task_id,))
    conn.commit()
    conn.close()
    if cursor.rowcount > 0:
        _emit({"type": "task_deleted", "task_id": task_id})
        return True
    return False


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def _rows_to_tasks(conn, rows) -> list[dict]:
    tasks = [_deserialize(dict(r)) for r in rows]
    histories = _load_histories(conn, [t["id"] for t in tasks])
    for task in tasks:
        task["history"] = histories.get(task["id"], [])
    return tasks


def get_task(task_id: int) -> dict | None:
    conn = _connect()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return None
    task = _rows_to_tasks(conn, [row])[0]
    conn.close()
    return task


def get_tasks_by_owner(chat_id: str, limit: int = 20) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE owner_chat_id=? ORDER BY created_at DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    tasks = _rows_to_tasks(conn, rows)
    conn.close()
    return tasks


def get_all_tasks(limit: int = 50) -> list[dict]:
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    tasks = _rows_to_tasks(conn, rows)
    conn.close()
    return tasks


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
    tasks = _rows_to_tasks(conn, rows)
    conn.close()
    return tasks


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
    tasks = _rows_to_tasks(conn, rows)
    conn.close()
    return tasks


def save_session(task_id: int, messages: list, plan: list | None = None,
                 current_step: int | None = None) -> None:
    """Persist the task's live agent thread (and optionally its todo list /
    progress) so a long-running task keeps full context and survives restarts.
    """
    fields: dict = {"messages": json.dumps(messages)}
    if plan is not None:
        fields["plan"] = json.dumps(plan)
    if current_step is not None:
        fields["current_step"] = current_step
    update_task(task_id, **fields)


def _deserialize(row: dict) -> dict:
    """Parse JSON fields back to Python objects."""
    for field in ("constraints", "plan", "history", "messages"):
        if isinstance(row.get(field), str):
            try:
                row[field] = json.loads(row[field])
            except (json.JSONDecodeError, TypeError):
                row[field] = {} if field == "constraints" else []
    return row
