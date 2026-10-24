"""测试夹具：每个用例独立工作区，互不污染。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shining_world.config.loader import settings_from_mapping  # noqa: E402
from shining_world.tools.bootstrap import build_service_from_settings  # noqa: E402
from shining_world.tools.facade import build_facade  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path):
    """最小配置：只有一个 mock 服务商，冷却清零便于断言。"""
    raw = {
        "workspace_root": str(tmp_path / "ws"),
        "default_provider": "mock-local",
        "use_mock_provider": True,
        "stream_defaults": {"cooldown_s": 0, "max_round_chars": 900, "auto_step": True},
        "snapshot": {"trigger_chars": 200, "keep_recent_chars": 80, "max_snapshots_in_context": 2},
        "retrieval": {"vector_dim": 128, "vector_top_k": 3},
    }
    return settings_from_mapping(raw, config_path=tmp_path / "config.yaml")


@pytest.fixture()
def service(settings):
    return build_service_from_settings(settings)


@pytest.fixture()
def facade(service):
    return build_facade(service)
