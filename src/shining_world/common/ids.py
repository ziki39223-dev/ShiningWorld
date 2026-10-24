"""ID 与时间工具。"""

from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import UTC, datetime


def new_id(prefix: str = "") -> str:
    """生成短 ID：``<prefix>_<12位十六进制>``。"""
    token = secrets.token_hex(6)
    return f"{prefix}_{token}" if prefix else token


def now_iso() -> str:
    """当前 UTC 时间戳（ISO8601，秒精度）。"""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def slugify(text: str, fallback: str = "item") -> str:
    """把任意文本压成可做目录名的 slug；中文保留（转为拼音不可靠，这里保留原字）。"""
    cleaned = unicodedata.normalize("NFKC", text).strip()
    cleaned = re.sub(r"[\s/\\:*?\"<>|]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or fallback
