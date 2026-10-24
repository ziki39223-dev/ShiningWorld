"""日志落盘测试：SSE/stdio 启动后应生成 logs/shining-world.log。"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from shining_world.entry.cli import _configure_logging


@pytest.fixture(autouse=True)
def _restore_logging():
    """每个用例结束后恢复 root logger，避免污染其他测试。"""
    root = logging.getLogger()
    saved = list(root.handlers)
    saved_level = root.level
    yield
    for handler in list(root.handlers):
        if handler not in saved:
            handler.close()
            root.removeHandler(handler)
    root.handlers[:] = saved
    root.setLevel(saved_level)


def test_log_file_created_and_written(tmp_path: Path):
    log_dir = tmp_path / "logs"
    _configure_logging("INFO", to_stderr=True, log_dir=log_dir)

    logging.getLogger("shining_world.test").info("日志落盘验证")

    log_file = log_dir / "shining-world.log"
    assert log_file.exists()
    assert "日志落盘验证" in log_file.read_text(encoding="utf-8")


def test_log_file_is_rotating_handler(tmp_path: Path):
    _configure_logging("INFO", to_stderr=True, log_dir=tmp_path / "logs")
    handlers = [
        h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert handlers[0].backupCount == 14
    assert str(handlers[0].baseFilename).endswith("shining-world.log")


def test_no_file_handler_without_log_dir(tmp_path: Path):
    _configure_logging("INFO", to_stderr=True)
    assert not any(
        isinstance(h, logging.handlers.TimedRotatingFileHandler)
        for h in logging.getLogger().handlers
    )


def test_unwritable_log_dir_does_not_raise(tmp_path: Path):
    """日志目录不可写时只降级到 stderr，不能拖垮服务启动。"""
    blocker = tmp_path / "blocked"
    blocker.write_text("我是个文件，不是目录", encoding="utf-8")

    _configure_logging("INFO", to_stderr=True, log_dir=blocker / "logs")
    logging.getLogger("shining_world.test").info("仍可正常记录")
    assert logging.getLogger().handlers
