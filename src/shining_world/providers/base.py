"""适配器抽象：所有服务商最终都归一成 ``complete(messages) -> text``。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class ProviderError(Exception):
    """服务商调用失败（网络、限流、鉴权、返回格式）。"""

    def __init__(self, message: str, *, retryable: bool = True, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.detail = detail or {}


@dataclass(slots=True)
class ChatMessage:
    role: str  # system / user / assistant
    content: str

    def to_payload(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class CompletionResult:
    text: str
    provider: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    attempts: int = 1


class Provider(ABC):
    """服务商适配器接口。"""

    name: str
    model: str

    @abstractmethod
    def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.85,
        max_tokens: int = 800,
    ) -> str:
        """返回补全文本；失败抛 ProviderError。"""

    def health_check(self) -> dict[str, Any]:
        """连通性测试默认实现：发一条极短请求。"""
        try:
            text = self.complete(
                [ChatMessage("user", "ping")],
                temperature=0.0,
                max_tokens=8,
            )
        except ProviderError as exc:
            return {"provider": self.name, "ok": False, "error": exc.message}
        return {"provider": self.name, "ok": True, "sample": text[:80]}
