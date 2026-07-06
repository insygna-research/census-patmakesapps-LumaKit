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
        "description": (
            "List Struqt projects (paged). Use query to find a project by name, and limit/offset to page "
            "through large sets. The response includes total, returned, hasMore, and nextOffset."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive substring to match project names."},
                "workspaceId": {"type": "string", "description": "Only return projects in this workspace id."},
                "limit": {"type": "integer", "description": "Max results (default 20, max 200)."},
                "offset": {"type": "integer", "description": "Results to skip for paging; use the response nextOffset for the next page."},
            },
        },
        "execute": lambda inputs: _request(
            "GET",
            "/v1/projects",
            params={
                "query": inputs.get("query"),
                "workspaceId": inputs.get("workspaceId"),
                "limit": inputs.get("limit"),
                "offset": inputs.get("offset"),
            },
        ),
    }


def get_struqt_list_tasks_tool():
    return {
        "name": "struqt_list_tasks",
        "description": (
            "List Struqt tasks/todos (paged). Filter by projectId and/or workspaceId, search titles with query, "
            "and page with limit/offset. The response includes total, returned, hasMore, and nextOffset."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "description": "Optional Struqt project id to filter tasks."},
                "workspaceId": {"type": "string", "description": "Optional workspace id to filter tasks."},
                "query": {"type": "string", "description": "Case-insensitive substring to match task titles."},
                "limit": {"type": "integer", "description": "Max results (default 20, max 200)."},
                "offset": {"type": "integer", "description": "Results to skip for paging; use the response nextOffset for the next page."},
            },
        },
        "execute": lambda inputs: _request(
            "GET",
            "/v1/todos",
            params={
                "projectId": inputs.get("projectId"),
                "workspaceId": inputs.get("workspaceId"),
                "query": inputs.get("query"),
                "limit": inputs.get("limit"),
                "offset": inputs.get("offset"),
            },
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


def _update_task(inputs: dict[str, Any]) -> dict[str, Any]:
    todo_id = inputs["todoId"]
    body = {k: v for k, v in inputs.items() if k != "todoId"}
    return _request("PATCH", f"/v1/todos/{todo_id}", json_body=body)


def get_struqt_delete_task_tool():
    return {
        "name": "struqt_delete_task",
        "description": "Delete a Struqt task/todo.",
        "inputSchema": {
            "type": "object",
            "properties": {"todoId": {"type": "string", "description": "Struqt todo id."}},
            "required": ["todoId"],
        },
        "execute": lambda inputs: _request("DELETE", f"/v1/todos/{inputs['todoId']}"),
    }


def get_struqt_list_workspaces_tool():
    return {
        "name": "struqt_list_workspaces",
        "description": (
            "List the workspaces the signed-in Struqt user belongs to (id, name, role), paged. "
            "Use query to find one by name, and limit/offset to page. "
            "Read-only: agents cannot create, rename, or delete workspaces or manage members. "
            "Use a workspace id to target struqt_create_group or struqt_create_project at a specific workspace."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive substring to match workspace names."},
                "limit": {"type": "integer", "description": "Max results (default 20, max 200)."},
                "offset": {"type": "integer", "description": "Results to skip for paging; use the response nextOffset for the next page."},
            },
        },
        "execute": lambda inputs: _request(
            "GET",
            "/v1/workspaces",
            params={
                "query": inputs.get("query"),
                "limit": inputs.get("limit"),
                "offset": inputs.get("offset"),
            },
        ),
    }


def get_struqt_list_groups_tool():
    return {
        "name": "struqt_list_groups",
        "description": (
            "List Struqt groups (paged). Use query to find a group by name, and limit/offset to page. "
            "The response includes total, returned, hasMore, and nextOffset."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive substring to match group names."},
                "workspaceId": {"type": "string", "description": "Only return groups in this workspace id."},
                "limit": {"type": "integer", "description": "Max results (default 20, max 200)."},
                "offset": {"type": "integer", "description": "Results to skip for paging; use the response nextOffset for the next page."},
            },
        },
        "execute": lambda inputs: _request(
            "GET",
            "/v1/groups",
            params={
                "query": inputs.get("query"),
                "workspaceId": inputs.get("workspaceId"),
                "limit": inputs.get("limit"),
                "offset": inputs.get("offset"),
            },
        ),
    }


def get_struqt_create_group_tool():
    return {
        "name": "struqt_create_group",
        "description": "Create a Struqt group. Prefer an existing group if one already matches the user's intent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Group name."},
                "parentGroupId": {
                    "type": "string",
                    "description": "Optional parent group id to nest under. Inherits the parent's workspace and scope.",
                },
                "workspaceId": {
                    "type": "string",
                    "description": "Optional workspace id (from struqt_list_workspaces) to create this group inside. Omit for a personal group. Ignored when parentGroupId is set.",
                },
                "storageScope": {
                    "type": "string",
                    "enum": ["local", "cloud"],
                    "description": "Storage scope for personal top-level groups. Defaults to local. Workspace groups are always cloud.",
                },
            },
            "required": ["name"],
        },
        "execute": _create_group,
    }


def _create_group(inputs: dict[str, Any]) -> dict[str, Any]:
    return _request(
        "POST",
        "/v1/groups",
        json_body={
            "name": inputs["name"],
            "parentGroupId": inputs.get("parentGroupId"),
            "workspaceId": inputs.get("workspaceId"),
            "storageScope": inputs.get("storageScope") or "local",
            "source": {"app": "lumakit"},
        },
    )


def get_struqt_update_group_tool():
    return {
        "name": "struqt_update_group",
        "description": "Rename a Struqt group or archive/unarchive it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "groupId": {"type": "string", "description": "Struqt group id."},
                "name": {"type": "string"},
                "archived": {"type": "boolean", "description": "true to archive, false to unarchive."},
            },
            "required": ["groupId"],
        },
        "execute": _update_group,
    }


def _update_group(inputs: dict[str, Any]) -> dict[str, Any]:
    group_id = inputs["groupId"]
    body = {k: v for k, v in inputs.items() if k != "groupId"}
    return _request("PATCH", f"/v1/groups/{group_id}", json_body=body)


def get_struqt_delete_group_tool():
    return {
        "name": "struqt_delete_group",
        "description": "Delete a Struqt group. Projects inside it are un-grouped (not deleted), matching the app.",
        "inputSchema": {
            "type": "object",
            "properties": {"groupId": {"type": "string", "description": "Struqt group id."}},
            "required": ["groupId"],
        },
        "execute": lambda inputs: _request("DELETE", f"/v1/groups/{inputs['groupId']}"),
    }


def get_struqt_update_project_tool():
    return {
        "name": "struqt_update_project",
        "description": "Rename a Struqt project, move it to a group, or archive/unarchive it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "description": "Struqt project id."},
                "name": {"type": "string"},
                "groupId": {"type": "string", "description": "Move to this group id, or empty string to ungroup."},
                "archived": {"type": "boolean"},
            },
            "required": ["projectId"],
        },
        "execute": _update_project,
    }


def _update_project(inputs: dict[str, Any]) -> dict[str, Any]:
    project_id = inputs["projectId"]
    body = {k: v for k, v in inputs.items() if k != "projectId"}
    return _request("PATCH", f"/v1/projects/{project_id}", json_body=body)


def get_struqt_delete_project_tool():
    return {
        "name": "struqt_delete_project",
        "description": "Delete a Struqt project and all of its tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {"projectId": {"type": "string", "description": "Struqt project id."}},
            "required": ["projectId"],
        },
        "execute": lambda inputs: _request("DELETE", f"/v1/projects/{inputs['projectId']}"),
    }
