"""OpenAI provider.

The ``openai`` SDK is an optional dependency (``repoheart[openai]``).
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

_DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(Provider):
    """Provider backed by the OpenAI Chat Completions API."""

    def __init__(
        self,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        try:
            import openai as _openai  # guarded import
        except ImportError as exc:
            raise ProviderError(
                "Install repoheart[openai] to use the openai provider"
            ) from exc

        self._openai = _openai
        self._client = _openai.OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url,
            timeout=timeout,
            max_retries=0,  # retry handled here
        )
        self._model = model or _DEFAULT_MODEL
        self._max_retries = max_retries

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        def _call() -> CompletionResponse:
            return self._do_complete(request)

        openai = self._openai
        return _retry_with_backoff(
            _call,
            max_retries=self._max_retries,
            exceptions=(
                openai.RateLimitError,
                openai.APIStatusError,
            ),
        )

    def supports_tools(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "openai"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _do_complete(self, request: CompletionRequest) -> CompletionResponse:
        openai = self._openai
        messages: list[dict[str, str]] = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        for msg in request.messages:
            messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": request.model or self._model,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.tools:
            kwargs["tools"] = [
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
            kwargs["tool_choice"] = "auto"

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise ProviderAuthError(f"OpenAI auth error: {exc}") from exc
        except openai.RateLimitError as exc:
            raise ProviderRateLimitError(f"OpenAI rate limit: {exc}") from exc
        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError(f"OpenAI timed out: {exc}") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderUnavailableError(
                    f"OpenAI server error {exc.status_code}"
                ) from exc
            raise ProviderError(f"OpenAI API error {exc.status_code}: {exc}") from exc

        return self._parse_response(resp)

    def _parse_response(self, resp: Any) -> CompletionResponse:
        choice = resp.choices[0] if resp.choices else None
        content = ""
        tool_calls: list[ToolCall] = []

        if choice is not None:
            msg = choice.message
            content = msg.content or ""
            for tc in msg.tool_calls or []:
                func = tc.function
                try:
                    import json

                    args = json.loads(func.arguments) if func.arguments else {}
                except Exception:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=func.name, arguments=args))

        finish_reason = choice.finish_reason if choice else "stop"
        usage = getattr(resp, "usage", None)
        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            model=getattr(resp, "model", ""),
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            finish_reason=finish_reason or "stop",
        )
