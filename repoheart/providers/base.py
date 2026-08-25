"""Provider abstraction — base types, ABC, error hierarchy, and retry utility.

All provider implementations and all callers (agents via AgentContext) depend
only on this module. No SDK-specific import ever appears here.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """A single conversational turn."""

    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class ToolDefinition:
    """Describes a callable tool exposed to the model."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass(frozen=True)
class ToolCall:
    """A single tool invocation returned by the model."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class CompletionRequest:
    """Everything a provider needs to fulfill a completion."""

    messages: list[Message]
    model: str
    tools: list[ToolDefinition] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.0  # deterministic default; override for creative tasks
    system: str = ""  # convenience system prompt (providers handle placement)
    metadata: dict[str, str] = field(default_factory=dict)  # for log correlation


@dataclass(frozen=True)
class CompletionResponse:
    """Normalised response from any provider."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""  # echoed model identifier
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "length" | "error"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """Base for all provider-boundary errors.

    The orchestrator catches this at the coarse level; agents can catch
    subclasses if they need to distinguish timeout vs. rate-limit.
    """


class ProviderTimeoutError(ProviderError):
    """Provider did not respond within the configured deadline."""


class ProviderRateLimitError(ProviderError):
    """Provider returned a rate-limit response after all retries."""


class ProviderAuthError(ProviderError):
    """Credentials are missing or rejected by the provider."""


class ProviderUnavailableError(ProviderError):
    """Provider returned a transient 5xx error after all retries."""


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class Provider(ABC):
    """Abstract interface for all AI provider backends.

    Concrete subclasses wrap a specific SDK. Every other component in
    RepoHeart depends only on this interface — never on any SDK import.
    """

    @abstractmethod
    def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Send a completion request and return the response.

        Implementations must raise a ``ProviderError`` subclass on any
        failure. Retry/backoff is the provider's responsibility.
        """
        ...

    @abstractmethod
    def supports_tools(self) -> bool:
        """Return True if this provider/model supports tool calling."""
        ...

    def provider_name(self) -> str:
        """Human-readable name for logging; defaults to class name."""
        return type(self).__name__


# ---------------------------------------------------------------------------
# Shared retry utility
# ---------------------------------------------------------------------------


def _retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_retries: int,
    base_delay: float = 1.0,
    exceptions: tuple[type[Exception], ...],
) -> T:
    """Call *fn* up to *max_retries* additional times on transient failures.

    Uses exponential backoff with full jitter, capped at 60 seconds.
    Raises the last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except exceptions as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            cap = min(base_delay * (2**attempt), 60.0)
            # Full jitter: sleep uniformly in [0, cap]
            import random

            time.sleep(random.uniform(0, cap))
    assert last_exc is not None
    raise last_exc
