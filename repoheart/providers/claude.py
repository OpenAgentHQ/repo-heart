"""Anthropic Claude provider.

The ``anthropic`` SDK is an optional dependency (``repoheart[claude]``).
The import is guarded: importing this module succeeds without the package;
instantiation raises ``ProviderError`` if it is absent.
"""

from __future__ import annotations

import os
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

_DEFAULT_MODEL = "claude-opus-4-5"


class ClaudeProvider(Provider):
    """Provider backed by the Anthropic Messages API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        try:
            import anthropic as _anthropic  # guarded import
        except ImportError as exc:
            raise ProviderError(
                "Install repoheart[claude] to use the claude provider"
            ) from exc

        self._anthropic = _anthropic
        self._client = _anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", ""),
            timeout=timeout,
            max_retries=0,  # retry handled here
        )
        self._model = model or _DEFAULT_MODEL
        self._max_retries = max_retries

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        def _call() -> CompletionResponse:
            return self._do_complete(request)

        anthropic = self._anthropic
        return _retry_with_backoff(
            _call,
            max_retries=self._max_retries,
            exceptions=(
                anthropic.RateLimitError,
                anthropic.APIStatusError,
            ),
        )

    def supports_tools(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "claude"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_complete(self, request: CompletionRequest) -> CompletionResponse:
        anthropic = self._anthropic
        messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request.messages
            if msg.role in ("user", "assistant")
        ]
        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.system:
            kwargs["system"] = request.system
        if request.tools:
            kwargs["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in request.tools
            ]

        try:
            resp = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ProviderAuthError(f"Claude auth error: {exc}") from exc
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimitError(f"Claude rate limit: {exc}") from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderTimeoutError(f"Claude timed out: {exc}") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderUnavailableError(f"Claude server error {exc.status_code}") from exc
            raise ProviderError(f"Claude API error {exc.status_code}: {exc}") from exc

        return self._parse_response(resp)

    def _parse_response(self, resp: Any) -> CompletionResponse:
        content = ""
        tool_calls: list[ToolCall] = []

        for block in resp.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        arguments=block.input if isinstance(block.input, dict) else {},
                    )
                )

        finish_reason = getattr(resp, "stop_reason", "stop") or "stop"
        usage = getattr(resp, "usage", None)
        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            model=getattr(resp, "model", ""),
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            finish_reason=finish_reason,
        )
