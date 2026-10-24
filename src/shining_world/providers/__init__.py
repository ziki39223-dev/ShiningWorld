"""模型适配器层：统一抽象 + OpenAI 兼容实现 + 本地 Mock。"""

from __future__ import annotations

from .base import ChatMessage, CompletionResult, Provider, ProviderError
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider
from .provider_manager import ProviderManager, build_manager

__all__ = [
    "ChatMessage",
    "CompletionResult",
    "Provider",
    "ProviderError",
    "MockProvider",
    "OpenAICompatProvider",
    "ProviderManager",
    "build_manager",
]
