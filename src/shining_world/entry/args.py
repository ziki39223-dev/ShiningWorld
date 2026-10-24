"""命令行参数解析。"""

from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shining-world",
        description="闪亮大世界 ShiningWorld · MCP 调度服务（stdio / SSE）",
    )
    parser.add_argument(
        "--config",
        default=str(Path("config.yaml").resolve()),
        help="config.yaml 路径（默认当前目录）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="SSE 监听端口（覆盖配置）",
    )
    parser.add_argument("--host", default=None, help="SSE 监听地址（覆盖配置）")
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="只打印解析后的配置，不启动服务",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="减少日志输出",
    )
    parser.add_argument(
        "--in-workspace",
        action="store_true",
        help="selfcheck 在真实工作区内跑（默认在临时目录，跑完清理）",
    )
    return parser


def overrides_from_args(args: argparse.Namespace) -> dict[str, object]:
    """把命令行覆盖项转成 dict（未指定的不写）。"""
    overrides: dict[str, object] = {}
    if getattr(args, "port", None) is not None:
        overrides["port"] = args.port
    if getattr(args, "host", None):
        overrides["host"] = args.host
    return overrides
