"""Anthropic (Claude) adapter via the official ``anthropic`` SDK.

Claude speaks the Messages API (its own schema), so this adapter maps
LumaKit's internal Ollama-style messages/tools to Anthropic content blocks
and back. Named ``anthropic_provider`` (not ``anthropic``) so the module can
import the SDK package without shadowing confusion.
"""

from __future__ import annotations

import itertools
import threading

from core.providers.base import (
    LLMClient,
    ProviderConnectionError,
    ProviderTimeoutError,
    run_interruptible,
    sniff_image_media_type,
    strip_internal_keys,
)

# Backpressure for bursty workloads (heartbeat + tasks + chat).
_REMOTE_CONCURRENCY = 4
_REMOTE_SLOTS = threading.Semaphore(_REMOTE_CONCURRENCY)

# Hard output ceiling per turn. Above ~16K the SDK wants streaming to avoid
# HTTP timeouts, and LumaKit turns are conversational-sized.
MAX_OUTPUT_TOKENS = 16000


class AnthropicClient(LLMClient):
    supports_tools_with_images = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        fallback_model: str | None = None,
        request_timeout: int = 120,
    ):
        super().__init__(fallback_model=fallback_model, request_timeout=request_timeout)
        self.name = "anthropic"
        try:
            import anthropic
        except ImportError as e:
            raise ProviderConnectionError(
                "The 'anthropic' package is required for LLM_PROVIDER=anthropic. "
                "Install it with: pip install anthropic"
            ) from e
        self._anthropic = anthropic
        kwargs: dict = {"timeout": float(request_timeout), "max_retries": 2}
        # A placeholder keeps construction from failing when no key is set yet
        # (e.g. before the user saves one in Settings); requests then 401 with
        # a clear "check LLM_API_KEY" message instead of crashing at startup.
        kwargs["api_key"] = api_key or "missing-api-key"
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)

    # ------------------------------------------------------------------
    # Conversion: internal Ollama-style -> Anthropic Messages
    # ------------------------------------------------------------------

    @staticmethod
    def _convert_tools(tools) -> list[dict]:
        converted = []
        for tool in tools or []:
            fn = tool.get("function") if isinstance(tool, dict) else None
            if not fn:
                continue
            converted.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return converted

    def _convert_messages(self, messages) -> tuple[str, list[dict]]:
        """Return (system_prompt, anthropic_messages)."""
        system_parts: list[str] = []
        out: list[dict] = []
        call_counter = itertools.count(1)
        pending_call_ids: list[str] = []

        for raw in messages:
            msg = strip_internal_keys(raw)
            role = msg.get("role")
            content = str(msg.get("content") or "")

            if role == "system":
                if content:
                    system_parts.append(content)
                continue

            if role == "assistant":
                blocks: list[dict] = []
                if content:
                    blocks.append({"type": "text", "text": content})
                if msg.get("tool_calls"):
                    pending_call_ids = []
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {}) or {}
                        call_id = tc.get("id") or f"toolu_synth_{next(call_counter)}"
                        pending_call_ids.append(call_id)
                        args = fn.get("arguments")
                        if not isinstance(args, dict):
                            import json as _json
                            try:
                                args = _json.loads(args) if isinstance(args, str) else {}
                            except Exception:
                                args = {}
                        blocks.append({
                            "type": "tool_use",
                            "id": call_id,
                            "name": fn.get("name", ""),
                            "input": args or {},
                        })
                if not blocks:
                    blocks.append({"type": "text", "text": ""})
                out.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                call_id = pending_call_ids.pop(0) if pending_call_ids else f"toolu_synth_{next(call_counter)}"
                result_block = {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": content,
                }
                # Parallel tool results must land in ONE user message.
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) \
                        and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                    out[-1]["content"].append(result_block)
                else:
                    out.append({"role": "user", "content": [result_block]})
                continue

            # user (and anything else) — may carry images
            if msg.get("images"):
                blocks = []
                for b64 in msg["images"]:
                    blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": sniff_image_media_type(b64),
                            "data": b64,
                        },
                    })
                blocks.append({"type": "text", "text": content or "What do you see in this image?"})
                out.append({"role": "user", "content": blocks})
            else:
                out.append({"role": "user", "content": content})

        # Messages API requires the first message to be a user turn.
        if not out or out[0]["role"] != "user":
            out.insert(0, {"role": "user", "content": "(session start)"})
        return "\n\n".join(system_parts), out

    @staticmethod
    def _convert_response(response) -> dict:
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in response.content or []:
            btype = getattr(block, "type", None)
            if btype == "text" and getattr(block, "text", None):
                text_parts.append(block.text)
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "function": {"name": block.name, "arguments": dict(block.input or {})},
                })

        content = "".join(text_parts)
        if response.stop_reason == "refusal" and not content:
            content = "I can't help with that request."

        message: dict = {"role": "assistant", "content": content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {
            "message": message,
            "done": True,
            "model": getattr(response, "model", None),
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": getattr(response.usage, "input_tokens", None),
                "output_tokens": getattr(response.usage, "output_tokens", None),
            },
        }

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    def _create_once(self, model, system, converted, tools, timeout):
        kwargs: dict = {
            "model": model,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": converted,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        return self._client.with_options(timeout=timeout).messages.create(**kwargs)

    def _create_with_fallback(self, model, system, converted, tools, timeout):
        a = self._anthropic
        try:
            return self._create_once(model, system, converted, tools, timeout), model
        except (a.APITimeoutError, a.APIConnectionError, a.InternalServerError, a.RateLimitError) as e:
            if not self.fallback_model or self.fallback_model == model:
                if isinstance(e, a.APITimeoutError):
                    raise ProviderTimeoutError(
                        f"Anthropic did not respond within {timeout}s"
                    ) from e
                raise ProviderConnectionError(f"Anthropic request failed: {e}") from e
            try:
                result = self._create_once(self.fallback_model, system, converted, tools, timeout)
                return result, self.fallback_model
            except a.APIError as fe:
                raise ProviderConnectionError(
                    f"Anthropic request failed for primary ({model}) and "
                    f"fallback ({self.fallback_model}): {fe}"
                ) from fe
        except a.AuthenticationError as e:
            raise ProviderConnectionError(
                "Anthropic rejected the API key (401). Check LLM_API_KEY."
            ) from e

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
        system, converted = self._convert_messages(messages)
        anthropic_tools = self._convert_tools(tools)

        def _request():
            acquired = False
            while not acquired:
                acquired = _REMOTE_SLOTS.acquire(timeout=0.5)
            try:
                return self._create_with_fallback(model, system, converted, anthropic_tools, timeout)
            finally:
                _REMOTE_SLOTS.release()

        response, used_model = run_interruptible(_request, check_interrupt)
        self.last_model_used = used_model
        result = self._convert_response(response)
        if stream and on_chunk:
            content = result.get("message", {}).get("content", "")
            if content:
                on_chunk(content)
        return result
