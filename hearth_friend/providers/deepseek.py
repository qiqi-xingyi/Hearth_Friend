"""DeepSeek provider.

The DeepSeek API is OpenAI-compatible, so the official SDK is pointed at a
different base_url rather than reimplemented. Retries, streaming and error types
come along with it.
"""

from __future__ import annotations

from typing import Iterator, Sequence

from hearth_friend.providers.base import Message, ProviderError


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        timeout: float = 60.0,
    ):
        if not api_key:
            raise ProviderError(
                "No API key. Set HEARTH_API_KEY in the environment or in .env "
                "(see .env.example)."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise ProviderError("the 'openai' package is required: pip install -e .") from exc

        self._client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self.model_id = model

    def generate(
        self, messages: Sequence[Message], *, temperature: float | None = None
    ) -> str:
        try:
            response = self._client.chat.completions.create(
                model=self.model_id,
                messages=list(messages),
                temperature=temperature,
            )
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
        return response.choices[0].message.content or ""

    def stream(
        self, messages: Sequence[Message], *, temperature: float | None = None
    ) -> Iterator[str]:
        try:
            stream = self._client.chat.completions.create(
                model=self.model_id,
                messages=list(messages),
                temperature=temperature,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                piece = chunk.choices[0].delta.content
                if piece:
                    yield piece
        except Exception as exc:
            raise ProviderError(str(exc)) from exc
