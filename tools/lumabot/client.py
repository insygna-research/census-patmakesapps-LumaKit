"""Thin HTTP client for the local LumaBot hardware daemon."""

from __future__ import annotations

import os
from typing import Any

import requests


DEFAULT_URL = "http://127.0.0.1:8971"


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 2.0,
) -> dict:
    base_url = os.getenv("LUMABOT_URL", DEFAULT_URL).rstrip("/")
    try:
        response = requests.request(
            method,
            f"{base_url}{path}",
            json=body,
            timeout=timeout,
        )
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {"error": "LumaBot is offline — is the LumaBot daemon running?"}

    if response.status_code >= 400:
        return {"error": payload.get("error") or f"LumaBot returned HTTP {response.status_code}"}
    return payload


def get_status() -> dict:
    return _request("GET", "/status")


def drive(direction: str, speed: float, duration_s: float) -> dict:
    return _request(
        "POST",
        "/drive",
        {"direction": direction, "speed": speed, "duration_s": duration_s},
    )


def stop() -> dict:
    return _request("POST", "/stop")


def set_indicator_activity(lease_id: str, active: bool, ttl_s: float) -> dict:
    return _request(
        "POST",
        "/indicator/activity",
        {"lease_id": lease_id, "active": active, "ttl_s": ttl_s},
        timeout=0.5,
    )
