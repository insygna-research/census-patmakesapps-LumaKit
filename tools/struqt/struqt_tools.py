from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


DEFAULT_STRUQT_URL = "http://127.0.0.1:47321"
INTEGRATION_FILE = Path.home() / ".project-todo-manager" / "integration.json"


class StruqtClientError(RuntimeError):
    pass


def _load_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    if INTEGRATION_FILE.exists():
        try:
            config = json.loads(INTEGRATION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}

    return {
        "url": os.getenv("STRUQT_API_URL")
        or f"http://{config.get('host') or '127.0.0.1'}:{config.get('port') or 47321}",
        "token": os.getenv("STRUQT_API_TOKEN") or config.get("token") or "",
    }


def _request(method: str, path: str, *, json_body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = _load_config()
    base_url = str(config["url"]).rstrip("/") or DEFAULT_STRUQT_URL
    token = str(config.get("token") or "")

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(
            method,
            f"{base_url}{path}",
            headers=headers,
            json=json_body,
            params={k: v for k, v in (params or {}).items() if v not in (None, "")},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise StruqtClientError(
            "Could not reach Struqt. Make sure the Struqt desktop app is running."
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text}

    if response.status_code >= 400:
        message = payload.get("error") if isinstance(payload, dict) else None
        raise StruqtClientError(message or f"Struqt returned HTTP {response.status_code}.")

    return payload


def get_struqt_health_tool():
    return {
        "name": "struqt_health",
        "description": "Check whether the Struqt desktop app local integration API is running.",
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: _request("GET", "/v1/health"),
    }


def get_struqt_connect_tool():
    return {
        "name": "struqt_connect",
        "description": (
            "Check Struqt integration setup and report whether LumaKit can connect. "
            "Use this before creating Struqt tasks if the user asks to connect or test Struqt."
        ),
        "inputSchema": {"type": "object", "properties": {}},
        "execute": _connect,
    }


def get_struct_connect_tool():
    tool = get_struqt_connect_tool()
    return {
        **tool,
        "name": "struct_connect",
        "description": (
            "Alias for struqt_connect. Use when the user says Struct, STruqt, Strukt, struq, "
            "or otherwise misspells Struqt while asking to connect or check setup."
        ),
    }


def _connect(inputs: dict[str, Any]) -> dict[str, Any]:
    config = _load_config()
    details = {
        "config_path": str(INTEGRATION_FILE),
        "api_url": config["url"],
        "has_token": bool(config.get("token")),
    }

    if not INTEGRATION_FILE.exists() and not os.getenv("STRUQT_API_TOKEN"):
        return {
            "connected": False,
            "needs_action": "Open Struqt, click LumaKit, and enable the local API.",
            **details,
        }

    if INTEGRATION_FILE.exists():
        try:
            raw_config = json.loads(INTEGRATION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw_config = {}

        if raw_config.get("enabled") is not True:
            return {
                "connected": False,
                "needs_action": "In Struqt, click LumaKit and press Enable.",
                **details,
            }

    try:
        health = _request("GET", "/v1/health")
    except StruqtClientError as exc:
        return {
            "connected": False,
            "needs_action": str(exc),
            **details,
        }

    return {
        "connected": True,
        "message": "LumaKit can connect to Struqt.",
        "health": health,
        **details,
    }


def get_struqt_list_projects_tool():
    return {
        "name": "struqt_list_projects",
        "description": "List Struqt projects that LumaKit can create tasks inside.",
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: _request("GET", "/v1/projects"),
    }


def get_struct_list_projects_tool():
    tool = get_struqt_list_projects_tool()
    return {
        **tool,
        "name": "struct_list_projects",
        "description": (
            "Alias for struqt_list_projects. Use when the user says Struct/Strukt/struq "
            "and wants projects from the Struqt TODO app."
        ),
    }


def get_struqt_list_tasks_tool():
    return {
        "name": "struqt_list_tasks",
        "description": "List Struqt tasks/todos, optionally filtered to a project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {
                    "type": "string",
                    "description": "Optional Struqt project id to filter tasks.",
                }
            },
        },
        "execute": lambda inputs: _request("GET", "/v1/todos", params={"projectId": inputs.get("projectId")}),
    }


def get_struct_list_tasks_tool():
    tool = get_struqt_list_tasks_tool()
    return {
        **tool,
        "name": "struct_list_tasks",
        "description": (
            "Alias for struqt_list_tasks. Use when the user says Struct/Strukt/struq "
            "and wants tasks from the Struqt TODO app."
        ),
    }


def get_struqt_create_project_tool():
    return {
        "name": "struqt_create_project",
        "description": "Create a Struqt project. Prefer using an existing project if one matches the user's request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name."},
                "groupId": {"type": "string", "description": "Optional group id."},
                "storageScope": {
                    "type": "string",
                    "enum": ["local", "cloud"],
                    "description": "Storage scope for ungrouped projects. Defaults to local.",
                },
            },
            "required": ["name"],
        },
        "execute": _create_project,
    }


def get_struct_create_project_tool():
    tool = get_struqt_create_project_tool()
    return {
        **tool,
        "name": "struct_create_project",
        "description": (
            "Alias for struqt_create_project. Use when the user says Struct/Strukt/struq "
            "and wants to create a project in the Struqt TODO app."
        ),
    }


def _create_project(inputs: dict[str, Any]) -> dict[str, Any]:
    return _request(
        "POST",
        "/v1/projects",
        json_body={
            "name": inputs["name"],
            "groupId": inputs.get("groupId"),
            "storageScope": inputs.get("storageScope") or "local",
            "source": {"app": "lumakit"},
        },
    )


def get_struqt_create_task_tool():
    return {
        "name": "struqt_create_task",
        "description": "Create a task/todo in an existing Struqt project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "description": "Target Struqt project id."},
                "title": {"type": "string", "description": "Short task title."},
                "description": {"type": "string", "description": "Task details or agent context."},
                "priority": {
                    "type": "integer",
                    "description": "Optional positive integer priority. Lower numbers appear higher.",
                },
                "assignedTo": {
                    "type": "string",
                    "description": "Optional Struqt/Supabase user id to assign the task to.",
                },
            },
            "required": ["projectId", "title"],
        },
        "execute": _create_task,
    }


def get_struct_create_task_tool():
    tool = get_struqt_create_task_tool()
    return {
        **tool,
        "name": "struct_create_task",
        "description": (
            "Alias for struqt_create_task. Use when the user says Struct/Strukt/struq "
            "and wants to create a task in the Struqt TODO app."
        ),
    }


def _create_task(inputs: dict[str, Any]) -> dict[str, Any]:
    return _request(
        "POST",
        "/v1/todos",
        json_body={
            "projectId": inputs["projectId"],
            "title": inputs["title"],
            "description": inputs.get("description") or "",
            "priority": inputs.get("priority"),
            "assignedTo": inputs.get("assignedTo"),
            "source": {"app": "lumakit"},
        },
    )


def get_struqt_update_task_tool():
    return {
        "name": "struqt_update_task",
        "description": "Update a Struqt task/todo title, description, done state, priority, or assignee.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "todoId": {"type": "string", "description": "Struqt todo id."},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "done": {"type": "boolean"},
                "priority": {"type": "integer"},
                "assignedTo": {"type": "string"},
            },
            "required": ["todoId"],
        },
        "execute": _update_task,
    }


def get_struct_update_task_tool():
    tool = get_struqt_update_task_tool()
    return {
        **tool,
        "name": "struct_update_task",
        "description": (
            "Alias for struqt_update_task. Use when the user says Struct/Strukt/struq "
            "and wants to update a task in the Struqt TODO app."
        ),
    }


def _update_task(inputs: dict[str, Any]) -> dict[str, Any]:
    todo_id = inputs["todoId"]
    body = {k: v for k, v in inputs.items() if k != "todoId"}
    return _request("PATCH", f"/v1/todos/{todo_id}", json_body=body)
