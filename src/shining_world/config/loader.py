"""config.yaml 加载器。"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from ..common.errors import ErrorCode, ToolError
from .settings import (
    AppSettings,
    ProviderConfig,
    RetrievalConfig,
    ServerConfig,
    SnapshotConfig,
    StreamDefaults,
)


def load_settings(config_path: str | Path) -> AppSettings:
    """读取并校验 config.yaml，返回 AppSettings。"""
    path = Path(config_path).expanduser().resolve()
    if not path.exists():
        raise ToolError(
            ErrorCode.NOT_FOUND,
            "配置文件不存在",
            {"path": str(path)},
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            "config.yaml 语法错误",
            {"path": str(path), "reason": str(exc)},
        ) from exc
    if not isinstance(raw, dict):
        raise ToolError(
            ErrorCode.INVALID_ARGUMENT,
            "config.yaml 顶层必须是映射",
            {"path": str(path)},
        )
    return settings_from_mapping(_expand_env(raw), config_path=path)


def _expand_env(value: Any) -> Any:
    """递归展开 ``${ENV_NAME}`` 占位符（API Key 走环境变量，避免明文入库）。"""
    if isinstance(value, str):
        return re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
            lambda m: os.environ.get(m.group(1), ""),
            value,
        )
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def settings_from_mapping(raw: dict[str, Any], config_path: Path) -> AppSettings:
    """把 YAML 映射转成 AppSettings（工作目录默认取配置文件所在目录）。"""
    workspace = Path(str(raw.get("workspace_root") or config_path.parent)).expanduser().resolve()

    providers = [
        ProviderConfig.from_mapping(item, ctx=f"providers[{index}]")
        for index, item in enumerate(raw.get("providers") or [])
        if isinstance(item, dict)
    ]

    retrieval_raw = raw.get("retrieval") or {}
    snapshot_raw = raw.get("snapshot") or {}
    stream_raw = raw.get("stream_defaults") or {}
    server_raw = raw.get("server") or {}

    default_provider = str(
        raw.get("default_provider")
        or next((p.name for p in sorted(providers, key=lambda p: p.priority)), "")
    )

    raw_use_mock = raw.get("use_mock_provider")
    use_mock = bool(raw_use_mock) if raw_use_mock is not None else not providers

    settings = AppSettings(
        workspace_root=workspace,
        config_path=config_path,
        mainline_outline=str(raw.get("mainline_outline") or ""),
        providers=providers,
        default_provider=default_provider,
        retrieval=RetrievalConfig(
            label_preferred=bool(retrieval_raw.get("label_preferred", True)),
            vector_fallback=bool(retrieval_raw.get("vector_fallback", True)),
            vector_fallback_min_tag_hits=int(retrieval_raw.get("vector_fallback_min_tag_hits", 1)),
            vector_dim=int(retrieval_raw.get("vector_dim", 512)),
            vector_top_k=int(retrieval_raw.get("vector_top_k", 6)),
            tag_top_k=int(retrieval_raw.get("tag_top_k", 20)),
            chunk_chars=int(retrieval_raw.get("chunk_chars", 400)),
        ),
        snapshot=SnapshotConfig(
            trigger_chars=int(snapshot_raw.get("trigger_chars", 6000)),
            keep_recent_chars=int(snapshot_raw.get("keep_recent_chars", 1200)),
            max_snapshots_in_context=int(snapshot_raw.get("max_snapshots_in_context", 2)),
        ),
        stream_defaults=StreamDefaults(
            cooldown_s=int(stream_raw.get("cooldown_s", 90)),
            max_round_chars=int(stream_raw.get("max_round_chars", 900)),
            auto_step=bool(stream_raw.get("auto_step", True)),
        ),
        server=ServerConfig(
            host=str(server_raw.get("host", "127.0.0.1")),
            port=int(server_raw.get("port", 8791)),
            sse_path=str(server_raw.get("sse_path", "/sse")),
            message_path=str(server_raw.get("message_path", "/messages/")),
            log_level=str(server_raw.get("log_level", "INFO")),
        ),
        use_mock_provider=use_mock,
        streams_preset=[p for p in (raw.get("streams_preset") or []) if isinstance(p, dict)],
    )
    settings.ensure_dirs()
    return settings
