"""服务商池：优先级、降级、限流、跳过无 Key 的服务商。"""

from __future__ import annotations

import pytest

from shining_world.common.errors import ToolError
from shining_world.config.settings import ProviderConfig
from shining_world.providers.base import ChatMessage, Provider, ProviderError
from shining_world.providers.provider_manager import ProviderManager, build_manager


class _Flaky(Provider):
    """前 N 次调用失败的服务商，用于验证自动降级。"""

    def __init__(self, name: str, fail_times: int = 1, retryable: bool = True) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.fail_times = fail_times
        self.retryable = retryable
        self.calls = 0

    def complete(self, messages, *, temperature=0.85, max_tokens=800) -> str:  # noqa: ANN001
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ProviderError(f"{self.name} 挂了", retryable=self.retryable)
        return f"[{self.name}] ok"


def _manager_with(*providers: Provider, priorities=None) -> ProviderManager:
    configs = []
    for index, provider in enumerate(providers):
        configs.append(
            ProviderConfig(
                name=provider.name,
                base_url="http://x",
                model=provider.model,
                priority=(priorities or {}).get(provider.name, 10 * (index + 1)),
            )
        )
    manager = ProviderManager(configs)
    for provider in providers:
        manager._states[provider.name].provider = provider  # noqa: SLF001 - 测试注入
    return manager


def test_falls_back_to_next_provider_on_error():
    bad = _Flaky("bad", fail_times=5)
    good = _Flaky("good", fail_times=0)
    manager = _manager_with(bad, good)

    result = manager.complete([ChatMessage("user", "hi")])
    assert result.provider == "good"
    assert result.attempts == 2
    assert bad.calls == 1


def test_all_failures_raise_provider_unavailable():
    manager = _manager_with(_Flaky("a", 9), _Flaky("b", 9))
    with pytest.raises(ToolError) as exc:
        manager.complete([ChatMessage("user", "hi")])
    assert exc.value.code == "PROVIDER_UNAVAILABLE"
    assert len(exc.value.detail["errors"]) == 2


def test_non_retryable_error_does_not_cool_down():
    manager = _manager_with(_Flaky("strict", fail_times=1, retryable=False), _Flaky("ok", 0))
    manager.complete([ChatMessage("user", "hi")])
    row = next(r for r in manager.list_public() if r["name"] == "strict")
    assert row["cooldown_s_left"] == 0
    assert row["failures"] == 1


def test_switch_default_and_quota():
    manager = _manager_with(_Flaky("a", 0), _Flaky("b", 0))
    assert manager.switch_default("b") == "b"
    assert manager.default_name() == "b"

    config = manager.set_quota("a", max_concurrency=1, rpm=5)
    assert (config.max_concurrency, config.rpm) == (1, 5)

    with pytest.raises(ToolError):
        manager.switch_default("不存在")


def test_mock_provider_is_appended_as_last_resort(settings):
    manager = build_manager(settings)
    names = [row["name"] for row in manager.list_public()]
    assert "mock-local" in names
    result = manager.complete([ChatMessage("user", "hi")])
    assert result.provider == "mock-local"


def test_providers_without_api_key_are_disabled(settings):
    from shining_world.config.loader import settings_from_mapping

    raw = {
        "workspace_root": str(settings.workspace_root),
        "providers": [
            {"name": "no-key", "base_url": "https://api.example.com/v1", "model": "m"},
        ],
    }
    local = settings_from_mapping(raw, config_path=settings.config_path)
    manager = build_manager(local)
    row = next(r for r in manager.list_public() if r["name"] == "no-key")
    assert row["enabled"] is False
    assert "api_key" in row["disabled_reason"]
