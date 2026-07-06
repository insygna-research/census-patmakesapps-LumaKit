"""Versioned-migration owner for the shared memory.db file (R-2).

Four stores share ``~/.lumakit/memory/memory.db`` (chat_store, memory_store,
email_draft_store, notifications). Each may CREATE ITS OWN tables/columns
idempotently, but ``PRAGMA user_version`` on this file is owned HERE and only
here — no store may read or bump it directly, or two migration schemes will
interact silently.

tasks.db is separate and its user_version is owned by core/task_store.py.
"""

from __future__ import annotations

import sqlite3

# Bump when adding a migration below.
MEMORY_DB_VERSION = 1


def run_versioned_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending versioned migrations. Caller commits."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]

    if version < 1:
        # v1 (moved from chat_store): backfill conversations.owner_id from the
        # active_chats pointer for rows created before owner scoping existed.
        # Both tables are created by chat_store before this runs; guard anyway
        # in case another store's connection reaches here first.
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if {"conversations", "active_chats"} <= tables:
            conn.execute("""
                UPDATE conversations
                   SET owner_id = (
                       SELECT user_id
                         FROM active_chats
                        WHERE active_chats.chat_id = conversations.id
                        ORDER BY active_chats.updated_at DESC
                        LIMIT 1
                   )
                 WHERE owner_id IS NULL
                   AND EXISTS (
                       SELECT 1 FROM active_chats WHERE active_chats.chat_id = conversations.id
                   )
            """)
            conn.execute("PRAGMA user_version = 1")

    # future migrations: if version < 2: ... conn.execute("PRAGMA user_version = 2")
