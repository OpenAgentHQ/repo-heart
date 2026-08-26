"""OpenRouter provider — unified API for 300+ models.

OpenRouter provides a single OpenAI-compatible endpoint
(https://openrouter.ai/api/v1) giving access to models from Anthropic,
Google, NVIDIA, xAI, and other providers. One API key, one billing
account, and automatic failover when a provider goes down.

No extra SDK required — pure HTTP + JSON, following the same pattern as
the OpenCode and OpenAI providers in this codebase.
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
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    ToolCall,
    _retry_with_backoff,
)


class OpenRouterProvider(Provider):
    """Provider backed by the OpenRouter unified API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model or "openrouter/auto"
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self._api_key:
            raise ProviderAuthError(
                "OpenRouter: OPENROUTER_API_KEY environment variable not set"
            )
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
        # OpenRouter relays tool calls; most models support it, but check
        # model capabilities if needed. Return True for now; callers can
        # inspect model names for tool-support guarantees.
        return True

    def provider_name(self) -> str:
        return "openrouter"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_complete(self, request: CompletionRequest) -> CompletionResponse:
        body = self._serialize(request)
        data = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            # OpenRouter requires these headers for routing and pricing
            "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", ""),
            "X-Title": os.environ.get("OPENROUTER_APP_NAME", "RepoHeart"),
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
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
                raise ProviderRateLimitError(
                    f"OpenRouter rate limit: {exc}"
                ) from exc
            if exc.code in (401, 403):
                raise ProviderAuthError(f"OpenRouter auth error: {exc}") from exc
            if exc.code >= 500:
                raise ProviderUnavailableError(
                    f"OpenRouter server error {exc.code}"
                ) from exc
            raise ProviderError(f"OpenRouter HTTP error {exc.code}") from exc
        except TimeoutError as exc:
            raise ProviderTimeoutError("OpenRouter request timed out") from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc).lower():
                raise ProviderTimeoutError("OpenRouter request timed out") from exc
            raise ProviderUnavailableError(f"OpenRouter URL error: {exc}") from exc

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
        # OpenRouter supports routing metadata
        if request.metadata:
            body["metadata"] = request.metadata
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