"""OpenCode provider — calls the OpenCode HTTP API via stdlib urllib.

No extra dependency required. API key read from the ``OPENCODE_API_KEY``
environment variable or passed directly.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from repoheart.providers.base import (
    CompletionRequest,
    CompletionResponse,
    Provider,
    ProviderAuthError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
    _retry_with_backoff,
)


class OpenCodeProvider(Provider):
    """Provider backed by the OpenCode HTTP API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str = "https://opencode.ai/zen/v1",
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model or "opencode-default"
        self._api_key = api_key or os.environ.get("OPENCODE_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        def _call() -> CompletionResponse:
            return self._do_complete(request)

        return _retry_with_backoff(
            _call,
            max_retries=self._max_retries,
            exceptions=(ProviderRateLimitError, ProviderUnavailableError),
        )

    def supports_tools(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "opencode"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_complete(self, request: CompletionRequest) -> CompletionResponse:
        body = self._serialize(request)
        data = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw: dict[str, Any] = json.loads(resp.read().decode())
                return self._parse_response(raw)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise ProviderRateLimitError(f"OpenCode rate limit: {exc}") from exc
            if exc.code in (401, 403):
                raise ProviderAuthError(f"OpenCode auth error: {exc}") from exc
            if exc.code >= 500:
                raise ProviderUnavailableError(f"OpenCode server error {exc.code}") from exc
            raise ProviderUnavailableError(f"OpenCode HTTP error {exc.code}") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("OpenCode request timed out") from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc).lower():
                raise ProviderTimeoutError("OpenCode request timed out") from exc
            raise ProviderUnavailableError(f"OpenCode URL error: {exc}") from exc

    def _serialize(self, request: CompletionRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        body: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in request.tools
            ]
        return body

    def _parse_response(self, raw: dict[str, Any]) -> CompletionResponse:
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        content: str = message.get("content") or ""
        finish_reason: str = choice.get("finish_reason", "stop") or "stop"

        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            raw_args = func.get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(
                ToolCall(id=tc.get("id", ""), name=func.get("name", ""), arguments=args)
            )

        usage = raw.get("usage", {})
        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            model=raw.get("model", ""),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            finish_reason=finish_reason,
        )
