"""轻量向量库：特征哈希 + TF 权重 + 余弦相似度，纯标准库、离线可用。

设计取舍：真正接嵌入模型会引入重依赖和网络成本；这里用 hashing trick 做
「字/词袋」向量，仅承担标签命中不足时的语义兜底，符合文档「向量仅兜底」定位。
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from pathlib import Path
from typing import Any

from ..common.jsonio import read_json, write_json

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']+|[一-鿿]")


def tokenize(text: str) -> list[str]:
    """英文按词、中文按单字切分（小语料下足够区分）。"""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def embed(text: str, dim: int = 512) -> dict[int, float]:
    """哈希到固定维度并做 L1 归一化，返回稀疏向量。"""
    counts: dict[int, float] = {}
    for token in tokenize(text):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        counts[index] = counts.get(index, 0.0) + 1.0
    total = sum(counts.values())
    if total:
        counts = {k: v / total for k, v in counts.items()}
    return counts


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    """稀疏余弦相似度。"""
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(index, 0.0) for index, value in a.items())
    if dot == 0.0:
        return 0.0
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


class VectorStore:
    """持久化向量库：``vector_db/index.json`` 存 ref/文本/稀疏向量/元数据。"""

    def __init__(self, path: Path, dim: int = 512) -> None:
        self.path = path
        self.dim = dim
        self._lock = threading.RLock()
        data = read_json(path, default={}) or {}
        self._rows: dict[str, dict[str, Any]] = data.get("rows", {})

    def save(self) -> None:
        with self._lock:
            write_json(self.path, {"dim": self.dim, "rows": self._rows})

    def upsert(
        self,
        ref: str,
        text: str,
        *,
        meta: dict[str, Any] | None = None,
    ) -> int:
        """写入/替换一条记录，返回稀疏向量维度大小。"""
        vector = embed(text, self.dim)
        with self._lock:
            self._rows[ref] = {
                "text": text,
                "vector": vector,
                "meta": dict(meta or {}),
            }
        return len(vector)

    def remove(self, ref: str) -> bool:
        with self._lock:
            return self._rows.pop(ref, None) is not None

    def count(self) -> int:
        with self._lock:
            return len(self._rows)

    def search(
        self,
        query: str,
        *,
        top_k: int = 6,
        allowed_factions: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """语义召回；allowed_factions 非空时按阵营过滤（None 的视为公共）。"""
        q = embed(query, self.dim)
        if not q:
            return []
        hits: list[dict[str, Any]] = []
        with self._lock:
            rows = list(self._rows.items())
        for ref, row in rows:
            faction = str(row.get("meta", {}).get("faction", "") or "")
            if allowed_factions is not None and faction and faction not in allowed_factions:
                continue
            score = cosine(q, row["vector"])
            if score <= 0.0:
                continue
            hits.append(
                {
                    "ref": ref,
                    "score": round(score, 4),
                    "text": row["text"],
                    "meta": dict(row.get("meta", {})),
                }
            )
        hits.sort(key=lambda h: (-h["score"], h["ref"]))
        return hits[:top_k]
