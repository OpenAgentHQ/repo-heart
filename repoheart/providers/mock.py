"""MockProvider — deterministic test double for the Provider ABC.

Never touches the network. Responses are looked up by the content of the
last user message; a default_response covers unmatched keys. Setting
``raise_on_complete`` lets tests exercise the orchestrator's error path.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from repoheart.providers.base import (
    CompletionRequest,
    CompletionResponse,
    Provider,
    ProviderError,
    ToolCall,
)


@dataclass
class CannedResponse:
    """A pre-defined response returned by MockProvider."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"


class MockProvider(Provider):
    """Deterministic, network-free Provider for use in tests.

    Usage::

        mock = MockProvider(default_response=CannedResponse("ok"))
        response = mock.complete(request)
        assert mock.call_count == 1
    """

    def __init__(
        self,
        responses: dict[str, CannedResponse] | None = None,
        default_response: CannedResponse | None = None,
        *,
        raise_on_complete: type[ProviderError] | None = None,
    ) -> None:
        self._responses: dict[str, CannedResponse] = responses or {}
        self._default = default_response
        self._raise_on_complete = raise_on_complete
        self.call_count: int = 0  # public; tests assert on this

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.call_count += 1

        if self._raise_on_complete is not None:
            raise self._raise_on_complete("MockProvider configured to raise")

        key = request.messages[-1].content if request.messages else ""
        canned = self._responses.get(key, self._default)

        if canned is None:
            raise ProviderError(
                f"MockProvider: no canned response for key {key!r} and no default set"
            )

        return CompletionResponse(
            content=canned.content,
            tool_calls=canned.tool_calls,
            model="mock",
            finish_reason=canned.finish_reason,
        )

    def supports_tools(self) -> bool:
        return True

    def provider_name(self) -> str:
        return "mock"
