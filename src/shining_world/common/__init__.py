"""通用工具：ID、错误信封、原子 JSON 读写、文本分句。"""

from __future__ import annotations

from .errors import ErrorCode, ToolError, ok, fail
from .ids import new_id, now_iso, slugify
from .jsonio import append_jsonl, read_json, read_jsonl, write_json
from .text import chunk_text, estimate_tokens, normalize_ws

__all__ = [
    "ErrorCode",
    "ToolError",
    "ok",
    "fail",
    "new_id",
    "now_iso",
    "slugify",
    "read_json",
    "write_json",
    "read_jsonl",
    "append_jsonl",
    "chunk_text",
    "estimate_tokens",
    "normalize_ws",
]
