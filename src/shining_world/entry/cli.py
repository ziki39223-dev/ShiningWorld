"""启动入口：``sse``（主推）/ ``stdio``（DSH 本地）/ ``selfcheck``。"""

from __future__ import annotations

import json
import logging
import logging.handlers
import shutil
import sys
import tempfile
from pathlib import Path

from ..common.errors import ToolError
from ..config.loader import load_settings
from ..config.settings import AppSettings
from ..server.app import SERVER_NAME, SERVER_VERSION, build_server
from ..tools.bootstrap import build_service_from_settings, persist_indexes
from .args import build_parser

_log = logging.getLogger("shining_world.entry")


def _configure_logging(
    level: str,
    *,
    to_stderr: bool,
    log_dir: Path | None = None,
) -> None:
    """统一日志配置：stdio 模式绝不能写 stdout（那是协议通道）。

    给了 ``log_dir`` 时额外挂一个按天轮转的文件 handler，
    落到 ``logs/shining-world.log``，保留 14 天。
    """
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler = logging.StreamHandler(sys.stderr if to_stderr else sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.TimedRotatingFileHandler(
                log_dir / "shining-world.log",
                when="midnight",
                backupCount=14,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError:
            # 日志落盘失败不能拖垮服务，stderr 仍然可用
            pass

    root.setLevel(getattr(logging, level.upper(), logging.INFO))


def _load(args) -> AppSettings:
    settings = load_settings(args.config)
    if args.port is not None:
        settings.server.port = int(args.port)
    if args.host:
        settings.server.host = str(args.host)
    if args.quiet:
        settings.server.log_level = "WARNING"
    return settings


def _banner(settings: AppSettings, transport: str) -> None:
    _log.info(
        "%s v%s 启动：transport=%s workspace=%s providers=%d",
        SERVER_NAME,
        SERVER_VERSION,
        transport,
        settings.workspace_root,
        len(settings.providers),
    )


def run_sse(argv: list[str] | None = None) -> int:
    """启动 SSE 服务（阻塞直到退出信号）。"""
    args = build_parser().parse_args(argv)
    try:
        settings = _load(args)
    except ToolError as exc:
        print(f"[启动失败] {exc.code}: {exc.message}", file=sys.stderr)
        print(json.dumps(exc.detail, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    if args.print_config:
        print(json.dumps(_settings_view(settings), ensure_ascii=False, indent=2))
        return 0

    _configure_logging(
        settings.server.log_level, to_stderr=True, log_dir=settings.logs_dir
    )
    _banner(settings, "sse")
    server = build_server(settings)
    _log.info(
        "SSE 端点：http://%s:%d%s（消息端点 %s）",
        settings.server.host,
        settings.server.port,
        settings.server.sse_path,
        settings.server.message_path,
    )
    try:
        server.run(
            transport="sse",
            host=settings.server.host,
            port=settings.server.port,
            sse_path=settings.server.sse_path,
            message_path=settings.server.message_path,
        )
    finally:
        _shutdown(server)
    return 0


def run_stdio(argv: list[str] | None = None) -> int:
    """启动 stdio 服务（stdout 只走协议）。"""
    args = build_parser().parse_args(argv)
    try:
        settings = _load(args)
    except ToolError as exc:
        print(f"[启动失败] {exc.code}: {exc.message}", file=sys.stderr)
        return 2

    if args.print_config:
        print(json.dumps(_settings_view(settings), ensure_ascii=False, indent=2))
        return 0

    _configure_logging(
        settings.server.log_level, to_stderr=True, log_dir=settings.logs_dir
    )
    _banner(settings, "stdio")
    server = build_server(settings)
    try:
        server.run(transport="stdio")
    finally:
        _shutdown(server)
    return 0


def run_selfcheck(argv: list[str] | None = None) -> int:
    """离线自检：装配服务 + 走一遍最小链路，不启动传输。

    默认在系统临时目录跑，不污染真实工作区（``--in-workspace`` 可改为原地跑）。
    """
    args = build_parser().parse_args(argv)
    try:
        settings = _load(args)
    except ToolError as exc:
        print(f"[自检失败] {exc.code}: {exc.message}", file=sys.stderr)
        return 2

    _configure_logging("WARNING", to_stderr=True)

    tmp_root = None
    if not getattr(args, "in_workspace", False):
        tmp_root = Path(tempfile.mkdtemp(prefix="shining-world-selfcheck-"))
        settings.workspace_root = tmp_root
        settings.ensure_dirs()

    try:
        return _run_selfcheck(settings)
    finally:
        if tmp_root is not None:
            shutil.rmtree(tmp_root, ignore_errors=True)


def _run_selfcheck(settings: AppSettings) -> int:
    service = build_service_from_settings(settings)
    from ..tools.facade import build_facade

    facade = build_facade(service)
    checks: list[dict[str, object]] = []

    def run(label: str, fn) -> None:
        result = fn()
        checks.append({"step": label, "ok": bool(result.get("ok")), "result": result})
        print(f"[{'OK' if result.get('ok') else 'FAIL'}] {label}", file=sys.stderr)

    run("service_status", facade.get_service_status)
    run("list_providers", facade.list_providers)
    run(
        "upsert_place",
        lambda: facade.upsert_place("自检地点", description="自检用地点", rules=["夜间禁止外出"]),
    )
    run(
        "approve_character_card",
        lambda: facade.approve_character_card(
            {
                "name": "自检角色",
                "identity": "测试用角色",
                "core_belief": "验证链路可用",
                "traits": {"stable": ["冷静"], "temporary": []},
                "hard_rule": ["禁止背后偷袭"],
            }
        ),
    )
    run("create_stream", lambda: facade.create_narrative_stream("自检支线", cell=5, cooldown_s=0))

    streams = service.streams.list()
    if streams:
        sid = streams[0].stream_id
        run("trigger_step", lambda: facade.trigger_stream_step(sid))
        run("get_content", lambda: facade.get_stream_content(sid))
        run("snapshot", lambda: facade.create_stream_snapshot(sid, summary="自检摘要"))
    else:
        checks.append({"step": "streams", "ok": False, "result": {"reason": "未创建支线"}})

    persist_indexes(service)
    failed = [c for c in checks if not c["ok"]]
    print(
        json.dumps(
            {"total": len(checks), "passed": len(checks) - len(failed), "failed": len(failed)},
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    return 0 if not failed else 1


def _settings_view(settings: AppSettings) -> dict[str, object]:
    return {
        "workspace_root": str(settings.workspace_root),
        "config_path": str(settings.config_path),
        "default_provider": settings.default_provider,
        "providers": [p.to_public() for p in settings.providers],
        "use_mock_provider": settings.use_mock_provider,
        "server": {
            "host": settings.server.host,
            "port": settings.server.port,
            "sse_path": settings.server.sse_path,
            "message_path": settings.server.message_path,
        },
        "stream_defaults": {
            "cooldown_s": settings.stream_defaults.cooldown_s,
            "max_round_chars": settings.stream_defaults.max_round_chars,
            "auto_step": settings.stream_defaults.auto_step,
        },
    }


def _shutdown(server: object) -> None:
    """退出清理：索引刷盘。"""
    service = getattr(server, "_sw_service", None)
    if service is None:
        return
    try:
        persist_indexes(service)
    except Exception as exc:  # noqa: BLE001 - 退出路径不允许再抛
        _log.warning("退出清理失败：%s", exc)


def main(argv: list[str] | None = None) -> int:
    """子命令分派：``sse``（默认）/ ``stdio`` / ``selfcheck``。"""
    raw = list(sys.argv[1:] if argv is None else argv)
    command = "sse"
    if raw and raw[0] in {"sse", "stdio", "selfcheck"}:
        command = raw.pop(0)
    if command == "stdio":
        return run_stdio(raw)
    if command == "selfcheck":
        return run_selfcheck(raw)
    return run_sse(raw)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
