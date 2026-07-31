"""Slash command handlers for the LumaKit CLI."""

import json
import os
import sys
from pathlib import Path

from core.chat_store import (
    delete_chat,
    get_chat_lumabot_profile,
    list_chats,
    load_chat,
    make_title,
    new_chat_id,
    save_chat,
    set_active_chat,
    set_chat_lumabot_profile,
)
from core.app_runtime_config import get_app_runtime_config, save_app_runtime_config
from core.identity import CLI_USER_ID
from core.runtime_config import apply_user_runtime
from core.cli import BOLD, CYAN, DIM, GREEN, RED, RESET, YELLOW, _c, render_storage_meter
from core.menu import select_menu
from tools.lumabot.remote import REMOTE_HELP, execute_remote_command


def handle_command(command: str, agent, session: dict) -> bool:
    """Dispatch a slash command. Returns True if handled, False if not a command."""
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    handlers = {
        "/help": cmd_help,
        "/chats": cmd_chats,
        "/new": cmd_new,
        "/status": cmd_status,
        "/config": cmd_config,
        "/clear": cmd_clear,
        "/lumabot": cmd_lumabot,
    }

    handler = handlers.get(cmd)
    if handler:
        handler(args, agent, session)
        return True
    else:
        print(_c(RED, f"  Unknown command: {cmd}"))
        print(_c(DIM, "  Type /help for available commands."))
        return True


def cmd_help(args: str, agent, session: dict):
    print(f"""
{_c(BOLD, '  LumaKit Commands')}

  {_c(CYAN, '/help')}                 Show this help
  {_c(CYAN, '/chats')}                List saved conversations
  {_c(CYAN, '/chats resume <id>')}    Resume a saved conversation
  {_c(CYAN, '/chats delete <id>')}    Delete a saved conversation
  {_c(CYAN, '/p [prompt]')}             Paste clipboard image to Lumi
  {_c(CYAN, '/image <path> [prompt]')} Send an image file to Lumi
  {_c(CYAN, '/new')}                  Start a new conversation
  {_c(CYAN, '/status')}               Show storage, index, and model info
  {_c(CYAN, '/config')}               View current configuration
  {_c(CYAN, '/config set <k> <v>')}   Update a config value
  {_c(CYAN, '/clear')}                Clear the screen
  {_c(CYAN, '/lumabot agent')}        Natural-language robot control
  {_c(CYAN, '/lumabot remote')}       Instant structured robot controls
  {_c(CYAN, '/lumabot off')}          Restore full LumaKit
""")


def cmd_chats(args: str, agent, session: dict):
    owner_id = session.get("owner_id", CLI_USER_ID)
    chats = list_chats(limit=20, owner_id=owner_id)
    if not chats:
        print(_c(DIM, "  No saved conversations.\n"))
        return

    # Build menu items
    items = []
    for chat in chats:
        updated = chat["updated_at"][:16].replace("T", " ")
        items.append({
            "label": chat["title"],
            "sublabel": f"id: {chat['id']}  |  {updated}",
            "chat_id": chat["id"],
        })

    # Print blank lines so first render has space to overwrite
    total_lines = 2 + len(items) * 2 + 1
    print("\n" * total_lines)

    result = select_menu(items, title="Saved Conversations")
    if not result:
        return

    if result.get("action") == "select":
        _chats_resume(result["chat_id"], agent, session)
    elif result.get("action") == "delete":
        _chats_delete(result["chat_id"], owner_id=owner_id)


def _chats_resume(chat_id: str, agent, session: dict):
    chat = load_chat(chat_id, owner_id=session.get("owner_id", CLI_USER_ID))
    if not chat:
        print(_c(RED, f"  Conversation '{chat_id}' not found."))
        return

    # Save current conversation first
    _auto_save(agent, session)

    # Load the resumed conversation
    agent.messages = chat["messages"]
    session["chat_id"] = chat["id"]
    session["title"] = chat["title"]
    session["first_message_sent"] = True
    set_active_chat(
        session.get("owner_id", CLI_USER_ID),
        session["chat_id"],
        scope=session.get("active_chat_scope"),
    )
    apply_user_runtime(agent, session, CLI_USER_ID, surface="cli")

    print(_c(GREEN, f"  Resumed: {chat['title']}"))
    print(_c(DIM, f"  {len(chat['messages'])} messages loaded.\n"))


def _chats_delete(chat_id: str, owner_id: str | None = None):
    chat = load_chat(chat_id, owner_id=owner_id)
    title = chat["title"] if chat else chat_id
    if delete_chat(chat_id, owner_id=owner_id):
        print(_c(GREEN, f"  Deleted: {title}"))
    else:
        print(_c(RED, f"  Conversation '{chat_id}' not found."))


def cmd_new(args: str, agent, session: dict):
    # Save current conversation
    _auto_save(agent, session)

    # Reset
    session["chat_id"] = new_chat_id()
    session["title"] = ""
    session["first_message_sent"] = False

    # Rebuild messages with just the system prompt
    agent.messages = [agent.build_system_message()]
    set_active_chat(
        session.get("owner_id", CLI_USER_ID),
        session["chat_id"],
        scope=session.get("active_chat_scope"),
    )
    apply_user_runtime(agent, session, CLI_USER_ID, surface="cli")

    print(_c(GREEN, "  New conversation started.\n"))


def cmd_status(args: str, agent, session: dict):
    health = agent.storage.check_health()
    meter = render_storage_meter(
        health["usage_percent"], health["total_display"], health["budget_display"]
    )

    index_status = agent.get_code_index_status()
    if index_status["state"] == "ready":
        index_display = f"{index_status['symbols']} symbols, {index_status['references']} references"
    elif index_status["state"] == "error":
        index_display = f"error: {index_status['error']}"
    else:
        index_display = index_status["state"]
    msg_count = len(agent.messages)
    model = agent.model or "not set"
    fallback = agent.fallback_model or "not set"
    chat_count = len(list_chats(limit=100, owner_id=session.get("owner_id", CLI_USER_ID)))

    print(f"""
{_c(BOLD, '  LumaKit Status')}

{meter}

  {_c(CYAN, 'Model:')}          {model}
  {_c(CYAN, 'Fallback:')}       {fallback}
  {_c(CYAN, 'Messages:')}       {msg_count} in current conversation
  {_c(CYAN, 'Saved chats:')}    {chat_count}
  {_c(CYAN, 'Index:')}          {index_display}
  {_c(CYAN, 'Chat ID:')}        {session.get('chat_id', 'none')}
""")

    for name, info in health["stores"].items():
        if info["size_bytes"] > 0:
            print(f"  {_c(DIM, f'{name}:')} {info['size_display']}")
    print()


def cmd_config(args: str, agent, session: dict):
    from core.paths import get_data_dir
    config_path = get_data_dir() / "config.json"

    if args.strip().lower().startswith("set"):
        _config_set(args, config_path, agent)
    else:
        _config_show(config_path, agent)


def _config_show(config_path: Path, agent):
    config = _load_config(config_path)

    print(f"\n{_c(BOLD, '  LumaKit Configuration')}")
    print(f"  {_c(DIM, str(config_path))}\n")

    defaults = _get_defaults(agent)
    for key, default in defaults.items():
        value = config.get(key, default)
        is_custom = key in config
        marker = _c(GREEN, "*") if is_custom else " "
        print(f"  {marker} {_c(CYAN, f'{key}:'):<35} {value}")

    print(f"\n{_c(DIM, '  * = customized  |  /config set <key> <value>')}\n")


def _config_set(args: str, config_path: Path, agent):
    # Parse: set <key> <value>
    parts = args.strip().split(maxsplit=2)
    if len(parts) < 3:
        print(_c(RED, "  Usage: /config set <key> <value>"))
        return

    key = parts[1]
    value = parts[2]

    # Type coercion
    int_keys = {"storage_budget_mb", "max_tool_rounds", "recent_turns"}
    bool_keys = {"auto_save_chats", "require_tool_approvals"}

    if key in int_keys:
        try:
            value = int(value)
        except ValueError:
            print(_c(RED, f"  {key} must be a number."))
            return
    elif key in bool_keys:
        value = value.lower() in ("true", "1", "yes")

    config = _load_config(config_path)
    if key == "require_tool_approvals":
        app_cfg = get_app_runtime_config().copy()
        app_cfg["require_tool_approvals"] = bool(value)
        save_app_runtime_config(app_cfg)
        print(_c(GREEN, f"  Set {key} = {value}"))
        return

    config[key] = value

    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    print(_c(GREEN, f"  Set {key} = {value}"))

    # Apply immediately where possible
    if key == "storage_budget_mb" and isinstance(value, int):
        agent.storage.budget_bytes = value * 1024 * 1024
    elif key == "max_tool_rounds" and isinstance(value, int):
        agent.MAX_TOOL_ROUNDS = value


def _load_config(config_path: Path) -> dict:
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _get_defaults(agent) -> dict:
    return {
        "model": agent.model or "(env: OLLAMA_MODEL)",
        "storage_budget_mb": agent.storage.budget_bytes // (1024 * 1024),
        "max_tool_rounds": agent.MAX_TOOL_ROUNDS,
        "auto_save_chats": True,
        "require_tool_approvals": bool(get_app_runtime_config().get("require_tool_approvals", True)),
    }


def cmd_clear(args: str, agent, session: dict):
    os.system("cls" if sys.platform == "win32" else "clear")


def cmd_lumabot(args: str, agent, session: dict):
    """Switch profiles or execute one deterministic remote command."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else ""
    current = get_chat_lumabot_profile(session.get("chat_id"))
    if not action:
        print(_c(CYAN, f"  LumaBot mode: {current.upper()}\n\n{REMOTE_HELP}\n"))
        return

    if action in {"on", "agent", "remote", "off"}:
        profile = "agent" if action == "on" else action
        set_chat_lumabot_profile(session.get("chat_id"), profile)
        apply_user_runtime(agent, session, CLI_USER_ID, surface="cli")
        labels = {
            "agent": "AGENT — natural language uses the configured LLM.",
            "remote": "REMOTE — structured commands bypass the LLM.",
            "off": "OFF — full LumaKit restored.",
        }
        print(_c(GREEN, f"  LumaBot mode {labels[profile]}\n"))
        if profile == "remote":
            print(f"{REMOTE_HELP}\n")
        return

    if action not in {"stop", "park", "status", "help"} and current != "remote":
        print(_c(RED, "  Switch to Remote mode first with /lumabot remote.\n"))
        return
    result = execute_remote_command(args)
    prefix = f"LumaBot mode: {current.upper()}\n" if action == "status" else ""
    color = GREEN if result.get("ok") else RED
    print(_c(color, f"  {prefix}{result['text']}\n"))


def _auto_save(agent, session: dict):
    """Save the current conversation if it has content."""
    if not session.get("first_message_sent"):
        return
    chat_id = session.get("chat_id", "")
    title = session.get("title", "Untitled")
    if len(agent.messages) > 1:
        save_chat(chat_id, title, agent.messages, owner_id=session.get("owner_id", CLI_USER_ID))
