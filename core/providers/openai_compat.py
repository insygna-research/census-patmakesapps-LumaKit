"""OpenAI-compatible chat adapter.

One code path covers OpenAI, xAI (Grok), and any other endpoint that speaks
``POST {base_url}/chat/completions`` — only base_url / model / key differ.
Local Ollama keeps its native client (core/providers factory routes
provider=ollama to OllamaClient, which retains the priority-gated local
scheduler); this adapter is for remote HTTP APIs, throttled by a modest
concurrency semaphore instead.
"""

from __future__ import annotations

import itertools
import json
import threading

import requests

from core.providers.base import (
    LLMClient,
    ProviderConnectionError,
    ProviderTimeoutError,
    run_interruptible,
    sniff_image_media_type,
    strip_internal_keys,
)

# Backpressure for bursty workloads; remote APIs handle parallelism fine.
_REMOTE_CONCURRENCY = 4
_REMOTE_SLOTS = threading.Semaphore(_REMOTE_CONCURRENCY)


class OpenAICompatClient(LLMClient):
    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        provider_name: str = "openai",
        fallback_model: str | None = None,
        request_timeout: int = 120,
    ):
        super().__init__(fallback_model=fallback_model, request_timeout=request_timeout)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = provider_name

    # ------------------------------------------------------------------
    # Message / tool conversion (internal Ollama-style <-> OpenAI wire)
    # ------------------------------------------------------------------

    def _convert_messages(self, messages) -> list[dict]:
        out: list[dict] = []
        call_counter = itertools.count(1)
        pending_call_ids: list[str] = []

        for raw in messages:
            msg = strip_internal_keys(raw)
            role = msg.get("role")
            content = msg.get("content") or ""

            if role == "assistant" and msg.get("tool_calls"):
                calls = []
                pending_call_ids = []
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {}) or {}
                    call_id = tc.get("id") or f"call_{next(call_counter)}"
                    pending_call_ids.append(call_id)
                    args = fn.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args or {})
                    calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {"name": fn.get("name", ""), "arguments": args},
                    })
                entry: dict = {"role": "assistant", "tool_calls": calls}
                if content:
                    entry["content"] = content
                out.append(entry)
            elif role == "tool":
                # LumaKit history doesn't carry OpenAI call ids; results are
                # appended in call order, so match positionally.
                call_id = pending_call_ids.pop(0) if pending_call_ids else f"call_{next(call_counter)}"
                out.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": str(content),
                })
            elif msg.get("images"):
                parts: list[dict] = []
                if content:
                    parts.append({"type": "text", "text": content})
                for b64 in msg["images"]:
                    media = sniff_image_media_type(b64)
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{b64}"},
                    })
                out.append({"role": role or "user", "content": parts})
            else:
                out.append({"role": role, "content": content})
        return out

    @staticmethod
    def _convert_response(data: dict) -> dict:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        message: dict = {
            "role": msg.get("role", "assistant"),
            "content": msg.get("content") or "",
        }
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    pass
            tool_calls.append({
                "id": tc.get("id"),
                "function": {"name": fn.get("name", ""), "arguments": args or {}},
            })
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "message": message,
            "done": True,
            "model": data.get("model"),
            "usage": data.get("usage"),
        }

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    def _post_once(self, model, messages, tools, options, timeout) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload: dict = {
            "model": model,
            "messages": self._convert_messages(messages),
        }
        if tools:
            payload["tools"] = tools  # already OpenAI function-tool format
        if options and options.get("temperature") is not None:
            payload["temperature"] = options["temperature"]
        response = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        if response.status_code == 401:
            raise ProviderConnectionError(
                f"{self.name} rejected the API key (401). Check LLM_API_KEY."
            )
        response.raise_for_status()
        return self._convert_response(response.json())

    def _post_with_fallback(self, model, messages, tools, options, timeout):
        try:
            return self._post_once(model, messages, tools, options, timeout), model
        except requests.Timeout as e:
            if not self.fallback_model or self.fallback_model == model:
                raise ProviderTimeoutError(
                    f"{self.name} did not respond within {timeout}s"
                ) from e
            try:
                result = self._post_once(self.fallback_model, messages, tools, options, timeout)
                return result, self.fallback_model
            except requests.Timeout as fe:
                raise ProviderTimeoutError(
                    f"{self.name} did not respond within {timeout}s for primary "
                    f"({model}) or fallback ({self.fallback_model})."
                ) from fe
            except (requests.ConnectionError, ConnectionRefusedError, OSError) as fe:
                raise ProviderConnectionError(
                    f"Cannot reach {self.name} at {self.base_url}."
                ) from fe
        except (requests.ConnectionError, ConnectionRefusedError, OSError) as e:
            if not self.fallback_model or self.fallback_model == model:
                raise ProviderConnectionError(
                    f"Cannot reach {self.name} at {self.base_url}."
                ) from e
            try:
                result = self._post_once(self.fallback_model, messages, tools, options, timeout)
                return result, self.fallback_model
            except (requests.Timeout, requests.ConnectionError, ConnectionRefusedError, OSError) as fe:
                raise ProviderConnectionError(
                    f"Cannot reach {self.name} at {self.base_url}: primary "
                    f"({model}) and fallback ({self.fallback_model}) both failed."
                ) from fe

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
        self.last_model_used = None
        timeout = self.request_timeout if deadline is None else max(1, float(deadline))

        def _request():
            acquired = False
            while not acquired:
                acquired = _REMOTE_SLOTS.acquire(timeout=0.5)
            try:
                return self._post_with_fallback(model, messages, tools, options, timeout)
            finally:
                _REMOTE_SLOTS.release()

        result, used_model = run_interruptible(_request, check_interrupt)
        self.last_model_used = used_model
        # Streaming is not implemented for remote providers yet; deliver the
        # full text once so on_chunk consumers still function.
        if stream and on_chunk:
            content = result.get("message", {}).get("content", "")
            if content:
                on_chunk(content)
        return result
