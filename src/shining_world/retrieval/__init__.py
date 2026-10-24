"""检索引擎：标签精确检索优先，向量语义召回兜底，阵营权限过滤。"""

from __future__ import annotations

from .engine import RetrievalEngine, RetrievalHit
from .tag_index import TagIndex, validate_tags
from .vector_store import VectorStore

__all__ = [
    "RetrievalEngine",
    "RetrievalHit",
    "TagIndex",
    "validate_tags",
    "VectorStore",
]
