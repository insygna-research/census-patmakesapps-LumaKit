"""Best-effort LumaBot thinking indicator for interactive LumaKit turns."""

from __future__ import annotations

import os
import threading
import uuid

from tools.lumabot import client


def _activity_enabled() -> bool:
    return os.getenv("LUMABOT_ACTIVITY_INDICATOR", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class LumaBotActivityLease:
    """Renew a unique activity lease without blocking the agent's work."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        ttl_s: float = 10.0,
        renew_s: float = 3.0,
        request_fn=None,
        lease_id: str | None = None,
    ):
        self.enabled = _activity_enabled() if enabled is None else enabled
        self.ttl_s = ttl_s
        self.renew_s = renew_s
        self.lease_id = lease_id or uuid.uuid4().hex
        self._request = request_fn or client.set_indicator_activity
        self._stop_event = threading.Event()
        self._thread = None

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"lumabot-activity-{self.lease_id[:8]}",
            daemon=True,
        )
        try:
            self._thread.start()
        except RuntimeError:
            self._thread = None

    def close(self) -> None:
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread and thread.is_alive():
            thread.join(timeout=1.25)

    def _send(self, active: bool) -> None:
        try:
            self._request(self.lease_id, active, self.ttl_s)
        except Exception:
            pass

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._send(True)
                if self._stop_event.wait(self.renew_s):
                    break
        finally:
            self._send(False)
