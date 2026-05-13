from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


DEFAULT_LUMALOK_URL = "http://127.0.0.1:47322"
INTEGRATION_FILE = Path.home() / ".lumalok" / "integration.json"


class LumalokClientError(RuntimeError):
    pass


def _load_config() -> dict[str, Any]:
    config: dict[str, Any] = {}
    if INTEGRATION_FILE.exists():
        try:
            config = json.loads(INTEGRATION_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}

    host = config.get("host") or "127.0.0.1"
    port = config.get("port") or 47322
    return {
        "enabled": config.get("enabled") is True,
        "url": os.getenv("LUMALOK_API_URL") or f"http://{host}:{port}",
        "token": os.getenv("LUMALOK_API_TOKEN") or config.get("token") or "",
    }


def _request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = _load_config()
    base_url = str(config["url"]).rstrip("/") or DEFAULT_LUMALOK_URL
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
        raise LumalokClientError(
            "Could not reach Lumalok. Make sure the Lumalok desktop app is running and the LumaKit integration is enabled."
        ) from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"error": response.text}

    if response.status_code >= 400:
        message = payload.get("error") if isinstance(payload, dict) else None
        raise LumalokClientError(message or f"Lumalok returned HTTP {response.status_code}.")

    return payload


def get_lumalok_connect_tool():
    return {
        "name": "lumalok_connect",
        "description": "Check whether LumaKit can connect to the Lumalok desktop app local integration API.",
        "inputSchema": {"type": "object", "properties": {}},
        "execute": _connect,
    }


def _connect(inputs: dict[str, Any]) -> dict[str, Any]:
    config = _load_config()
    details = {
        "config_path": str(INTEGRATION_FILE),
        "api_url": config["url"],
        "has_token": bool(config.get("token")),
        "enabled": bool(config.get("enabled")),
    }

    if not INTEGRATION_FILE.exists() and not os.getenv("LUMALOK_API_TOKEN"):
        return {
            "connected": False,
            "needs_action": "Open Lumalok, unlock the vault, go to Settings, and enable LumaKit Integration.",
            **details,
        }

    if not config.get("enabled") and not os.getenv("LUMALOK_API_TOKEN"):
        return {
            "connected": False,
            "needs_action": "In Lumalok Settings, enable LumaKit Integration.",
            **details,
        }

    try:
        health = _request("GET", "/v1/health")
    except LumalokClientError as exc:
        return {
            "connected": False,
            "needs_action": str(exc),
            **details,
        }

    return {
        "connected": True,
        "message": "LumaKit can connect to Lumalok.",
        "health": health,
        **details,
    }


def get_lumalok_overview_tool():
    return {
        "name": "lumalok_overview",
        "description": "Get Lumalok vault overview counts and expiring secret metadata. Requires the vault to be unlocked.",
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: _request("GET", "/v1/overview"),
    }


def get_lumalok_list_projects_tool():
    return {
        "name": "lumalok_list_projects",
        "description": "List Lumalok projects and secret counts. Requires the vault to be unlocked.",
        "inputSchema": {"type": "object", "properties": {}},
        "execute": lambda inputs: _request("GET", "/v1/projects"),
    }


def get_lumalok_create_project_tool():
    return {
        "name": "lumalok_create_project",
        "description": "Create a Lumalok project. Prefer using an existing project if one matches the user's request.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Project name."},
            },
            "required": ["name"],
        },
        "execute": lambda inputs: _request("POST", "/v1/projects", json_body={"name": inputs["name"]}),
    }


def get_lumalok_list_secrets_tool():
    return {
        "name": "lumalok_list_secrets",
        "description": (
            "List Lumalok secret metadata, optionally filtered by project or query. "
            "Does not return secret values unless includeValues is true."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "projectId": {"type": "string", "description": "Optional Lumalok project id."},
                "q": {"type": "string", "description": "Optional search query."},
                "includeValues": {
                    "type": "boolean",
                    "description": "Return raw secret values. Use only when the user explicitly asks to reveal values.",
                },
            },
        },
        "execute": lambda inputs: _request(
            "GET",
            "/v1/secrets",
            params={
                "projectId": inputs.get("projectId"),
                "q": inputs.get("q"),
                "includeValues": "true" if inputs.get("includeValues") else "",
            },
        ),
    }


def get_lumalok_get_secret_tool():
    return {
        "name": "lumalok_get_secret",
        "description": (
            "Get one Lumalok secret by id. Raw value is omitted unless reveal is true; "
            "use reveal only when the user explicitly asks for the secret value."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "secretId": {"type": "string", "description": "Lumalok secret id."},
                "reveal": {"type": "boolean", "description": "Whether to return the raw secret value."},
            },
            "required": ["secretId"],
        },
        "execute": lambda inputs: _request(
            "GET",
            f"/v1/secrets/{inputs['secretId']}",
            params={"reveal": "true" if inputs.get("reveal") else ""},
        ),
    }


def get_lumalok_add_secret_tool():
    return {
        "name": "lumalok_add_secret",
        "description": "Add a secret to Lumalok. Can target an existing project id or create/use a project by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Secret title."},
                "value": {"type": "string", "description": "Secret value."},
                "projectId": {"type": "string", "description": "Optional existing Lumalok project id."},
                "projectName": {"type": "string", "description": "Optional project name to create or reuse."},
                "category": {"type": "string", "description": "Optional category such as API Key, Password, Token."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
                "expiry": {"type": "string", "description": "Optional YYYY-MM-DD expiry date."},
            },
            "required": ["title", "value"],
        },
        "execute": _add_secret,
    }


def _add_secret(inputs: dict[str, Any]) -> dict[str, Any]:
    body = {k: v for k, v in inputs.items() if v not in (None, "")}
    return _request("POST", "/v1/secrets", json_body=body)


def get_lumalok_update_secret_tool():
    return {
        "name": "lumalok_update_secret",
        "description": "Update Lumalok secret metadata or value by id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "secretId": {"type": "string", "description": "Lumalok secret id."},
                "title": {"type": "string"},
                "value": {"type": "string"},
                "projectId": {"type": "string"},
                "category": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "note": {"type": "string"},
                "expiry": {"type": "string", "description": "Optional YYYY-MM-DD expiry date."},
            },
            "required": ["secretId"],
        },
        "execute": _update_secret,
    }


def _update_secret(inputs: dict[str, Any]) -> dict[str, Any]:
    secret_id = inputs["secretId"]
    body = {k: v for k, v in inputs.items() if k != "secretId" and v is not None}
    return _request("PATCH", f"/v1/secrets/{secret_id}", json_body=body)
