"""配置数据结构。

刻意不用 pydantic：只有 mcp / PyYAML 两个硬依赖，降低部署门槛。
校验在 ``from_mapping`` 里集中做，出错统一抛 ToolError。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common.errors import ErrorCode, ToolError


def _require(mapping: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in mapping:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            f"配置缺少必填项：{ctx}.{key}",
            {"context": ctx, "key": key},
        )
    return mapping[key]


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class ProviderConfig:
    """单个 OpenAI 兼容服务商。"""

    name: str
    base_url: str
    api_key: str = ""
    model: str = "gpt-4o-mini"
    tier: str = "paid"  # paid / free
    priority: int = 100  # 越小越先
    max_concurrency: int = 2
    rpm: int = 60
    timeout_s: float = 60.0
    enabled: bool = True
    kind: str = "openai"  # openai / mock
    allow_empty_key: bool = False  # 某些内网/免费网关无需 api_key
    extra_headers: dict[str, str] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: dict[str, Any], ctx: str = "providers") -> ProviderConfig:
        name = str(_require(raw, "name", ctx))
        return cls(
            name=name,
            base_url=str(raw.get("base_url", "")),
            api_key=str(raw.get("api_key", "") or ""),
            model=str(raw.get("model", "gpt-4o-mini")),
            tier=str(raw.get("tier", "paid")),
            priority=_as_int(raw.get("priority"), 100),
            max_concurrency=max(1, _as_int(raw.get("max_concurrency"), 2)),
            rpm=max(1, _as_int(raw.get("rpm"), 60)),
            timeout_s=max(1.0, _as_float(raw.get("timeout_s"), 60.0)),
            enabled=bool(raw.get("enabled", True)),
            kind=str(raw.get("kind", "openai")),
            allow_empty_key=bool(raw.get("allow_empty_key", False)),
            extra_headers={str(k): str(v) for k, v in (raw.get("extra_headers") or {}).items()},
            params=dict(raw.get("params") or {}),
        )

    def to_public(self) -> dict[str, Any]:
        """对外展示用：隐藏 api_key。"""
        row = {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "tier": self.tier,
            "priority": self.priority,
            "max_concurrency": self.max_concurrency,
            "rpm": self.rpm,
            "timeout_s": self.timeout_s,
            "enabled": self.enabled,
            "kind": self.kind,
            "has_api_key": bool(self.api_key),
        }
        reason = self.params.get("_disabled_reason")
        if reason:
            row["disabled_reason"] = reason
        return row


@dataclass(slots=True)
class RetrievalConfig:
    label_preferred: bool = True
    vector_fallback: bool = True
    vector_fallback_min_tag_hits: int = 1  # 标签命中少于此数才启动向量兜底
    vector_dim: int = 512
    vector_top_k: int = 6
    tag_top_k: int = 20
    chunk_chars: int = 400


@dataclass(slots=True)
class SnapshotConfig:
    trigger_chars: int = 6000
    keep_recent_chars: int = 1200
    max_snapshots_in_context: int = 2


@dataclass(slots=True)
class StreamDefaults:
    cooldown_s: int = 90
    max_round_chars: int = 900
    auto_step: bool = True


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8791
    sse_path: str = "/sse"
    message_path: str = "/messages/"
    log_level: str = "INFO"


@dataclass(slots=True)
class AppSettings:
    workspace_root: Path
    config_path: Path
    mainline_outline: str = ""
    providers: list[ProviderConfig] = field(default_factory=list)
    default_provider: str = ""
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    stream_defaults: StreamDefaults = field(default_factory=StreamDefaults)
    server: ServerConfig = field(default_factory=ServerConfig)
    streams_preset: list[dict[str, Any]] = field(default_factory=list)
    use_mock_provider: bool = True

    # ---- 派生路径 ----
    @property
    def world_dir(self) -> Path:
        return self.workspace_root / "world-bible"

    @property
    def vector_dir(self) -> Path:
        return self.workspace_root / "vector_db"

    @property
    def streams_dir(self) -> Path:
        return self.workspace_root / "streams"

    @property
    def logs_dir(self) -> Path:
        return self.workspace_root / "logs"

    @property
    def proposals_path(self) -> Path:
        return self.world_dir / "proposals.json"

    def ensure_dirs(self) -> None:
        for path in (
            self.world_dir / "plot",
            self.world_dir / "map",
            self.world_dir / "culture",
            self.world_dir / "character",
            self.vector_dir,
            self.streams_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
