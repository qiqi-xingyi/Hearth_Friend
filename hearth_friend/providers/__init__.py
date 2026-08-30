"""Model providers."""

from __future__ import annotations

from hearth_friend.config import Config
from hearth_friend.providers.base import Message, ModelProvider, ProviderError

__all__ = ["Message", "ModelProvider", "ProviderError", "build_provider"]


def build_provider(config: Config) -> ModelProvider:
    if config.provider == "deepseek":
        from hearth_friend.providers.deepseek import DeepSeekProvider

        return DeepSeekProvider(
            config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout=config.request_timeout,
        )
    raise ProviderError(f"unknown provider: {config.provider!r} (set HEARTH_PROVIDER)")
