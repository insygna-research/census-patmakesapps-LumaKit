import json
import sqlite3
import uuid
from datetime import datetime

from core.paths import get_data_dir


DB_PATH = get_data_dir() / "memory" / "memory.db"


def _connect():
    from core.db import connect as db_connect
    conn = db_connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            owner_id TEXT,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            messages TEXT NOT NULL,
            display_messages TEXT
        )
    """)
    # Per-user "active chat" pointer — lets any surface resume the current
    # conversation on connect so Telegram ↔ web feels continuous.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_chats (
            user_id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_chat_scopes (
            user_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, scope)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_workspaces (
            chat_id TEXT PRIMARY KEY,
            owner_id TEXT,
            workspace_path TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_runtime_modes (
            chat_id TEXT PRIMARY KEY,
            lumabot_enabled INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)")}
    if "owner_id" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN owner_id TEXT")
        columns.add("owner_id")
    if "display_messages" not in columns:
        conn.execute("ALTER TABLE conversations ADD COLUMN display_messages TEXT")
        columns.add("display_messages")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_owner_updated ON conversations(owner_id, updated_at)")
    # memory.db's user_version is owned by core/memory_db.py — never touch the
    # pragma from individual stores (R-2).
    from core.memory_db import run_versioned_migrations
    run_versioned_migrations(conn)
    conn.commit()
    return conn


def set_active_chat(user_id: str, chat_id: str, scope: str | None = None) -> None:
    """Mark this chat as the user's current active conversation."""
    if not user_id or not chat_id:
        return
    conn = _connect()
    now = datetime.now().isoformat()
    if scope:
        conn.execute(
            "INSERT INTO active_chat_scopes (user_id, scope, chat_id, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id, scope) DO UPDATE SET chat_id = excluded.chat_id, updated_at = excluded.updated_at",
            (str(user_id), str(scope), str(chat_id), now),
        )
    else:
        conn.execute(
            "INSERT INTO active_chats (user_id, chat_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id, updated_at = excluded.updated_at",
            (str(user_id), str(chat_id), now),
        )
    conn.commit()
    conn.close()


def get_active_chat(user_id: str, scope: str | None = None) -> str | None:
    """Return the user's current active chat id, or None if never set."""
    if not user_id:
        return None
    conn = _connect()
    if scope:
        row = conn.execute(
            "SELECT chat_id FROM active_chat_scopes WHERE user_id = ? AND scope = ?",
            (str(user_id), str(scope)),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT chat_id FROM active_chats WHERE user_id = ?", (str(user_id),)
        ).fetchone()
    conn.close()
    return row["chat_id"] if row else None


def save_chat(
    chat_id: str,
    title: str,
    messages: list[dict],
    owner_id: str | None = None,
    display_messages: list[dict] | None = None,
) -> str:
    """Save or update a conversation. Returns the chat id."""
    conn = _connect()
    now = datetime.now().isoformat()
    messages_json = json.dumps(messages, default=str)
    display_messages_json = (
        json.dumps(display_messages, default=str)
        if display_messages is not None
        else None
    )
    owner = str(owner_id) if owner_id is not None else None

    existing = conn.execute(
        "SELECT id FROM conversations WHERE id = ?", (chat_id,)
    ).fetchone()

    if existing:
        if display_messages is None:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ?, messages = ?, owner_id = COALESCE(?, owner_id) WHERE id = ?",
                (title, now, messages_json, owner, chat_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ?, messages = ?, display_messages = ?, owner_id = COALESCE(?, owner_id) WHERE id = ?",
                (title, now, messages_json, display_messages_json, owner, chat_id),
            )
    else:
        conn.execute(
            "INSERT INTO conversations (id, owner_id, title, created_at, updated_at, messages, display_messages) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, owner, title, now, now, messages_json, display_messages_json),
        )

    conn.commit()
    conn.close()
    return chat_id


def load_chat(chat_id: str, owner_id: str | None = None) -> dict | None:
    """Load a conversation by id. Returns dict with id, title, messages, etc."""
    conn = _connect()
    if owner_id is None:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (chat_id,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND owner_id = ?",
            (chat_id, str(owner_id)),
        ).fetchone()
    conn.close()

    if not row:
        return None

    messages = json.loads(row["messages"])
    display_messages = None
    if row["display_messages"]:
        try:
            display_messages = json.loads(row["display_messages"])
        except (TypeError, json.JSONDecodeError):
            display_messages = None

    return {
        "id": row["id"],
        "owner_id": row["owner_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "messages": messages,
        "display_messages": display_messages if display_messages is not None else messages,
    }


def list_chats(limit: int = 20, owner_id: str | None = None) -> list[dict]:
    """List recent conversations, newest first."""
    conn = _connect()
    if owner_id is None:
        rows = conn.execute(
            "SELECT id, owner_id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, owner_id, title, created_at, updated_at FROM conversations WHERE owner_id = ? ORDER BY updated_at DESC LIMIT ?",
            (str(owner_id), limit),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_chat(chat_id: str, owner_id: str | None = None) -> bool:
    """Delete a conversation. Returns True if it existed."""
    conn = _connect()
    if owner_id is None:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (chat_id,))
    else:
        cursor = conn.execute(
            "DELETE FROM conversations WHERE id = ? AND owner_id = ?",
            (chat_id, str(owner_id)),
        )
    if cursor.rowcount > 0:
        conn.execute("DELETE FROM chat_workspaces WHERE chat_id = ?", (chat_id,))
        conn.execute("DELETE FROM chat_runtime_modes WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()
    return cursor.rowcount > 0


def set_chat_workspace(chat_id: str, workspace_path: str, owner_id: str | None = None) -> None:
    if not chat_id or not workspace_path:
        return
    conn = _connect()
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO chat_workspaces (chat_id, owner_id, workspace_path, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET owner_id = excluded.owner_id, workspace_path = excluded.workspace_path, updated_at = excluded.updated_at",
        (str(chat_id), str(owner_id) if owner_id is not None else None, str(workspace_path), now),
    )
    conn.commit()
    conn.close()


def get_chat_workspace(chat_id: str, owner_id: str | None = None) -> str | None:
    if not chat_id:
        return None
    conn = _connect()
    if owner_id is None:
        row = conn.execute(
            "SELECT workspace_path FROM chat_workspaces WHERE chat_id = ?",
            (str(chat_id),),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT workspace_path FROM chat_workspaces WHERE chat_id = ? AND (owner_id = ? OR owner_id IS NULL)",
            (str(chat_id), str(owner_id)),
        ).fetchone()
    conn.close()
    return row["workspace_path"] if row else None


def set_chat_lumabot_mode(chat_id: str, enabled: bool) -> None:
    """Persist the focused LumaBot profile for one conversation."""
    if not chat_id:
        return
    conn = _connect()
    conn.execute(
        "INSERT INTO chat_runtime_modes (chat_id, lumabot_enabled, updated_at) "
        "VALUES (?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET "
        "lumabot_enabled = excluded.lumabot_enabled, updated_at = excluded.updated_at",
        (str(chat_id), int(bool(enabled)), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_chat_lumabot_mode(chat_id: str | None) -> bool:
    """Return whether this conversation uses the focused LumaBot profile."""
    if not chat_id:
        return False
    conn = _connect()
    row = conn.execute(
        "SELECT lumabot_enabled FROM chat_runtime_modes WHERE chat_id = ?",
        (str(chat_id),),
    ).fetchone()
    conn.close()
    return bool(row["lumabot_enabled"]) if row else False


def list_known_workspaces(limit: int = 10) -> list[str]:
    """Distinct workspace paths any chat has used, most recently used first."""
    conn = _connect()
    rows = conn.execute(
        "SELECT workspace_path, MAX(updated_at) AS last_used FROM chat_workspaces "
        "GROUP BY workspace_path ORDER BY last_used DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    conn.close()
    return [r["workspace_path"] for r in rows]


def iter_chats_with_messages(owner_id: str | None = None) -> list[dict]:
    """Return saved conversations with messages for read-only search."""
    conn = _connect()
    if owner_id is None:
        rows = conn.execute(
            "SELECT id, owner_id, title, created_at, updated_at, messages, display_messages FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, owner_id, title, created_at, updated_at, messages, display_messages FROM conversations WHERE owner_id = ? ORDER BY updated_at DESC",
            (str(owner_id),),
        ).fetchall()
    conn.close()

    chats = []
    for row in rows:
        try:
            messages = json.loads(row["messages"])
        except (TypeError, json.JSONDecodeError):
            messages = []
        display_messages = None
        if row["display_messages"]:
            try:
                display_messages = json.loads(row["display_messages"])
            except (TypeError, json.JSONDecodeError):
                display_messages = None
        chats.append({
            "id": row["id"],
            "owner_id": row["owner_id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": messages,
            "display_messages": display_messages if display_messages is not None else messages,
        })
    return chats


def new_chat_id() -> str:
    """Generate a short chat id."""
    return uuid.uuid4().hex[:8]


def make_title(first_message: str) -> str:
    """Auto-generate a title from the first user message."""
    title = first_message.strip().replace("\n", " ")
    if len(title) > 50:
        title = title[:47] + "..."
    return title
