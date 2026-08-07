"""Provider-agnostic LLM client interface.

Every provider client exposes the same duck-typed surface the rest of LumaKit
already speaks (it grew out of ``OllamaClient``):

- ``chat(model, messages, tools=None, stream=False, deadline=None,
  options=None, check_interrupt=None, priority="normal", on_chunk=None)``
  returning an Ollama-style response dict:
  ``{"message": {"role", "content", "tool_calls": [...]}, ...}``
- ``last_model_used`` / ``fallback_model`` attributes
- ``tags()`` for local model discovery (empty for remote providers)

Messages use LumaKit's internal (Ollama-style) shape:
``{"role", "content", "images": [b64]?, "tool_calls"?, "name"?}`` plus
bookkeeping keys like ``created_at`` that adapters must strip before sending.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod

# Canonical provider exceptions. These are the same classes the codebase has
# always caught from ollama_client, re-exported under provider-neutral names
# so existing except-clauses keep working across every provider.
from ollama_client import (
    OllamaConnectionError as ProviderConnectionError,
    OllamaInterruptedError as ProviderInterruptedError,
    OllamaRequestError as ProviderRequestError,
    OllamaTimeoutError as ProviderTimeoutError,
    http_error_detail,
)

__all__ = [
    "LLMClient",
    "ProviderConnectionError",
    "ProviderInterruptedError",
    "ProviderRequestError",
    "ProviderTimeoutError",
    "http_error_detail",
    "run_interruptible",
    "strip_internal_keys",
    "sniff_image_media_type",
]

# Keys LumaKit adds to messages for its own bookkeeping — not part of any
# provider wire format.
_INTERNAL_MESSAGE_KEYS = {"created_at", "tool_image"}


class LLMClient(ABC):
    """Abstract provider client."""

    name: str = "unknown"
    supports_tools: bool = True
    supports_vision: bool = True
    # Whether the provider reliably handles tool definitions and images in the
    # same request. Cloud providers do; several local vision models misbehave,
    # so the native Ollama path keeps the historical no-tools image turns.
    supports_tools_with_images: bool = False

    def __init__(self, *, fallback_model: str | None = None, request_timeout: int = 120):
        self.fallback_model = fallback_model
        self.request_timeout = request_timeout
        self.last_model_used: str | None = None

    @abstractmethod
    def chat(
        self,
        model,
        messages,
        tools=None,
        stream=False,
        deadline=None,
        options=None,
        check_interrupt=None,
        priority="normal",
        on_chunk=None,
    ) -> dict:
        """Send a chat request and return an Ollama-style response dict."""

    def tags(self, request_timeout=None) -> dict:
        """Installed-model discovery. Only meaningful for local providers."""
        return {"models": []}


def run_interruptible(fn, check_interrupt):
    """Run *fn* on a worker thread, polling *check_interrupt* every 100ms.

    Mirrors OllamaClient's interrupt pattern so /stop keeps working on every
    provider. Without a callback, runs inline.
    """
    if not check_interrupt:
        return fn()

    outcome: dict = {}
    done = threading.Event()

    def _run():
        try:
            outcome["result"] = fn()
        except Exception as exc:  # noqa: BLE001 — re-raised on the caller thread
            outcome["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    while not done.wait(0.1):
        try:
            if check_interrupt():
                raise ProviderInterruptedError("Interrupted by /stop.")
        except ProviderInterruptedError:
            raise
        except Exception:
            continue

    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def strip_internal_keys(message: dict) -> dict:
    return {k: v for k, v in message.items() if k not in _INTERNAL_MESSAGE_KEYS}


def sniff_image_media_type(b64_data: str) -> str:
    """Best-effort media type from a base64 image payload's magic bytes."""
    import base64

    try:
        head = base64.b64decode(b64_data[:32] + "=" * (-len(b64_data[:32]) % 4))
    except Exception:
        return "image/png"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF":
        return "image/webp"
    return "image/png"
