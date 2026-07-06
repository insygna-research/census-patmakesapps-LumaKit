"""Shared SQLite connection helper (R-1/R-3).

Every store connects through here so concurrency settings can't drift:
WAL journaling lets the task-runner thread write while web/Telegram read,
and the 5s busy timeout absorbs short lock contention instead of raising
"database is locked".
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

BUSY_TIMEOUT_MS = 5000

# Converting a fresh DB from the default journal mode to WAL needs a moment of
# exclusive access; when several threads open a brand-new file simultaneously
# the conversion can race and surface as "database is locked". Serialize the
# first-connection setup per file within this process. WAL is persistent in
# the file, so later connections skip the conversion entirely.
_setup_lock = threading.Lock()
_wal_ready: set[str] = set()


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    # BEGIN IMMEDIATE for implicit transactions: a deferred transaction that
    # reads first and upgrades to a write returns "database is locked"
    # instantly (the busy handler is never consulted on upgrades). Taking the
    # write lock up front makes contention wait out busy_timeout instead.
    conn.isolation_level = "IMMEDIATE"
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")

    key = str(path.resolve())
    if key not in _wal_ready:
        with _setup_lock:
            if key not in _wal_ready:
                for attempt in range(10):
                    try:
                        conn.execute("PRAGMA journal_mode=WAL")
                        break
                    except sqlite3.OperationalError:
                        if attempt == 9:
                            raise
                        time.sleep(0.05 * (attempt + 1))
                _wal_ready.add(key)
    else:
        conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
