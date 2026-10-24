"""原子 JSON / JSONL 读写。

写入一律「临时文件 + 替换」，避免支线运行中写半截文件导致 DSH 读到坏数据。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .errors import ErrorCode, ToolError


def read_json(path: Path, default: Any = None) -> Any:
    """读 JSON；文件不存在时返回 default。"""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(
            ErrorCode.IO_ERROR,
            f"JSON 解析失败：{path.name}",
            {"path": str(path), "reason": str(exc)},
        ) from exc


def write_json(path: Path, data: Any) -> None:
    """原子写 JSON（UTF-8，保留中文）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    except OSError as exc:
        Path(tmp).unlink(missing_ok=True)
        raise ToolError(
            ErrorCode.IO_ERROR,
            f"写入失败：{path.name}",
            {"path": str(path), "reason": str(exc)},
        ) from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读 JSONL；坏行跳过。"""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    """追加一行 JSONL。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
