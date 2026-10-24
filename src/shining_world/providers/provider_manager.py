"""多服务商调度：优先级、并发上限、速率窗口、失败自动切换。

线程安全：支线可能并行步进，因此每次取号/记录都加锁。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..common.errors import ErrorCode, ToolError
from ..config.settings import AppSettings, ProviderConfig
from .base import ChatMessage, CompletionResult, Provider, ProviderError
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider


@dataclass
class _ProviderState:
    """单个服务商的运行时状态。"""

    provider: Provider
    config: ProviderConfig
    active: int = 0
    failures: int = 0
    cooldown_until: float = 0.0
    calls: int = 0
    hits: int = 0
    recent: deque[float] = field(default_factory=deque)
    last_error: str = ""

    def available(self, now: float) -> bool:
        if not self.config.enabled:
            return False
        if now < self.cooldown_until:
            return False
        if self.active >= self.config.max_concurrency:
            return False
        window = self.recent
        while window and now - window[0] > 60.0:
            window.popleft()
        return len(window) < self.config.rpm


class ProviderManager:
    """服务商池：按 priority 排序，失败次数越多越靠后，冷却后自动回归。"""

    def __init__(self, configs: list[ProviderConfig], default_name: str = "") -> None:
        self._lock = threading.RLock()
        self._states: dict[str, _ProviderState] = {}
        self._default_name = default_name
        for config in configs:
            self._states[config.name] = _ProviderState(
                provider=self._make_provider(config),
                config=config,
            )

    # ---- 构建 ----
    @staticmethod
    def _make_provider(config: ProviderConfig) -> Provider:
        if config.kind == "mock":
            return MockProvider(name=config.name, model=config.model)
        return OpenAICompatProvider(config)

    def add(self, config: ProviderConfig) -> None:
        with self._lock:
            self._states[config.name] = _ProviderState(
                provider=self._make_provider(config),
                config=config,
            )

    # ---- 查询 ----
    def list_public(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        with self._lock:
            rows = []
            for state in self._states.values():
                row = state.config.to_public()
                row.update(
                    {
                        "active": state.active,
                        "calls": state.calls,
                        "failures": state.failures,
                        "available": state.available(now),
                        "cooldown_s_left": max(0, int(state.cooldown_until - now)),
                        "last_error": state.last_error,
                    }
                )
                rows.append(row)
            return sorted(rows, key=lambda r: (r["priority"], r["name"]))

    def default_name(self) -> str:
        with self._lock:
            if self._default_name and self._default_name in self._states:
                return self._default_name
            ordered = self._ordered(now=time.monotonic())
            return ordered[0].config.name if ordered else ""

    def switch_default(self, name: str) -> str:
        with self._lock:
            if name not in self._states:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"服务商不存在：{name}",
                    {"available": sorted(self._states)},
                )
            self._default_name = name
            return name

    def set_quota(self, name: str, *, max_concurrency: int | None, rpm: int | None) -> ProviderConfig:
        with self._lock:
            state = self._states.get(name)
            if state is None:
                raise ToolError(ErrorCode.NOT_FOUND, f"服务商不存在：{name}", {"available": sorted(self._states)})
            if max_concurrency is not None:
                state.config.max_concurrency = max(1, int(max_concurrency))
            if rpm is not None:
                state.config.rpm = max(1, int(rpm))
            return state.config

    def test_connection(self, name: str | None = None) -> dict[str, Any]:
        with self._lock:
            names = [name] if name else list(self._states)
        results = []
        for item in names:
            state = self._states.get(item)
            if state is None:
                results.append({"provider": item, "ok": False, "error": "服务商不存在"})
                continue
            results.append(state.provider.health_check())
        return {"ok": all(r.get("ok") for r in results), "results": results}

    # ---- 调度 ----
    def _ordered(self, now: float) -> list[_ProviderState]:
        """可用优先 → priority 升序 → 失败次数升序。"""
        states = list(self._states.values())
        return sorted(
            (s for s in states if s.available(now)),
            key=lambda s: (s.config.priority, s.failures, s.config.name),
        )

    def complete(
        self,
        messages: list[ChatMessage] | list[dict[str, str]],
        *,
        temperature: float = 0.85,
        max_tokens: int = 800,
        prefer: str | None = None,
        max_attempts: int = 3,
    ) -> CompletionResult:
        """依次尝试可用服务商，失败自动降级到下一个。

        messages 既接受 ``ChatMessage``，也接受 ``{"role","content"}`` 字典。
        """
        normalized = _normalize_messages(messages)
        attempts = 0
        errors: list[dict[str, str]] = []
        candidates: list[_ProviderState] = []

        with self._lock:
            now = time.monotonic()
            if prefer:
                preferred = self._states.get(prefer)
                if preferred is not None and preferred.available(now):
                    candidates.append(preferred)
            candidates.extend(
                state for state in self._ordered(now) if state not in candidates
            )
            if not candidates:
                raise ToolError(
                    ErrorCode.PROVIDER_UNAVAILABLE,
                    "没有可用服务商（全部冷却或已达并发上限）",
                    {"providers": self.list_public()},
                )
            # 只对真实服务商做次数限制；mock 兜底永远排在最后一名候选
            real = [s for s in candidates if s.config.kind != "mock"]
            mocks = [s for s in candidates if s.config.kind == "mock"]
            candidates = real[:max_attempts] + mocks
            for state in candidates:
                state.active += 1
                state.recent.append(now)

        try:
            for state in candidates:
                attempts += 1
                started = time.perf_counter()
                try:
                    text = state.provider.complete(
                        normalized,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                except ProviderError as exc:
                    with self._lock:
                        state.failures += 1
                        state.last_error = exc.message
                        if exc.retryable:
                            state.cooldown_until = time.monotonic() + min(120.0, 10.0 * state.failures)
                    errors.append({"provider": state.config.name, "error": exc.message})
                    continue
                except Exception as exc:  # noqa: BLE001 - 适配器实现不可控
                    with self._lock:
                        state.failures += 1
                        state.last_error = str(exc)
                    errors.append({"provider": state.config.name, "error": str(exc)})
                    continue

                latency = int((time.perf_counter() - started) * 1000)
                with self._lock:
                    state.calls += 1
                    state.hits += 1
                    state.failures = 0
                return CompletionResult(
                    text=text,
                    provider=state.config.name,
                    model=state.config.model,
                    latency_ms=latency,
                    attempts=attempts,
                )
        finally:
            with self._lock:
                for state in candidates:
                    state.active = max(0, state.active - 1)

        raise ToolError(
            ErrorCode.PROVIDER_UNAVAILABLE,
            f"全部服务商调用失败（尝试 {attempts} 次）",
            {"errors": errors},
        )


def _normalize_messages(
    messages: list[ChatMessage] | list[dict[str, str]],
) -> list[ChatMessage]:
    """把字典形式的消息统一成 ChatMessage。"""
    normalized: list[ChatMessage] = []
    for item in messages:
        if isinstance(item, ChatMessage):
            normalized.append(item)
            continue
        normalized.append(
            ChatMessage(
                role=str(item.get("role", "user")),
                content=str(item.get("content", "")),
            )
        )
    return normalized


def build_manager(settings: AppSettings) -> ProviderManager:
    """按配置装配服务商池；无真实服务商时挂一个本地 Mock 保证可跑。"""
    configs = list(settings.providers)
    # 未注入 API Key 的服务商自动跳过，避免每次调用都白跑一次失败
    for config in configs:
        if config.kind == "openai" and not config.api_key and not config.allow_empty_key:
            config.enabled = False
            config.params.setdefault("_disabled_reason", "缺少 api_key（环境变量未注入）")
    if settings.use_mock_provider and not any(c.kind == "mock" for c in configs):
        configs.append(
            ProviderConfig(
                name="mock-local",
                base_url="",
                model="mock-1",
                tier="free",
                priority=999,
                kind="mock",
            )
        )
    if not configs:
        configs.append(
            ProviderConfig(name="mock-local", base_url="", model="mock-1", kind="mock")
        )
    manager = ProviderManager(configs, default_name=settings.default_provider)
    return manager
