"""Model provider protocol.

The model is a replaceable compute resource, so everything above this line talks
to the protocol rather than to a vendor.

This declares only what M0 actually calls. Structured output and a reasoning tier
get added when something needs them, not in anticipation.
"""

from __future__ import annotations

from typing import Iterator, Protocol, Sequence, TypedDict, runtime_checkable


class Message(TypedDict):
    role: str
    content: str


class ProviderError(RuntimeError):
    """The provider could not produce a response."""


@runtime_checkable
class ModelProvider(Protocol):
    model_id: str

    def generate(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str: ...

    def stream(
        self, messages: Sequence[Message], *, temperature: float | None = None
    ) -> Iterator[str]: ...

    def structured_output(
        self, messages: Sequence[Message], *, temperature: float | None = None
    ) -> dict: ...
