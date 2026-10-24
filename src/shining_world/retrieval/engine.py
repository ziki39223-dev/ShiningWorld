"""检索编排：标签优先 → 不足时向量兜底 → 阵营权限过滤。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config.settings import RetrievalConfig
from .tag_index import TagIndex
from .vector_store import VectorStore


@dataclass(slots=True)
class RetrievalHit:
    ref: str
    source: str  # tag / vector
    score: float
    tags: list[str] = field(default_factory=list)
    text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        row = {
            "ref": self.ref,
            "source": self.source,
            "score": self.score,
            "tags": list(self.tags),
            "meta": dict(self.meta),
        }
        if self.text:
            row["text"] = self.text[:400]
        return row


class RetrievalEngine:
    """标签/向量融合检索。"""

    def __init__(
        self,
        tag_index: TagIndex,
        vector_store: VectorStore,
        config: RetrievalConfig,
    ) -> None:
        self.tags = tag_index
        self.vectors = vector_store
        self.config = config

    def search(
        self,
        tags: list[str],
        query: str = "",
        *,
        faction_scope: set[str] | None = None,
        match_all: bool = True,
    ) -> dict[str, Any]:
        """返回 ``{strategy, hits, tag_hits, vector_hits}``。"""
        allowed = faction_scope
        tag_rows = self._tag_search(tags, match_all=match_all, allowed=allowed)
        hits = [RetrievalHit(row["ref"], "tag", 1.0, row["tags"], "", row["meta"]) for row in tag_rows]

        used_vector = False
        # 向量只在标签命中不足时兜底——这是文档要求的确定性检索策略
        if (
            self.config.vector_fallback
            and len(hits) < max(1, self.config.vector_fallback_min_tag_hits)
            and query
        ):
            used_vector = True
            seen = {hit.ref for hit in hits}
            for row in self.vectors.search(
                query,
                top_k=self.config.vector_top_k,
                allowed_factions=allowed,
            ):
                if row["ref"] in seen:
                    continue
                hits.append(
                    RetrievalHit(
                        row["ref"],
                        "vector",
                        float(row["score"]),
                        self.tags.tags_of(row["ref"]),
                        row["text"],
                        row["meta"],
                    )
                )

        if tag_rows and used_vector:
            strategy = "tag+vector"
        elif tag_rows:
            strategy = "tag"
        elif used_vector:
            strategy = "vector"
        else:
            strategy = "empty"

        return {
            "strategy": strategy,
            "tags": tags,
            "tag_hits": len(tag_rows),
            "vector_hits": sum(1 for h in hits if h.source == "vector"),
            "hits": [hit.to_public() for hit in hits],
        }

    # ---- 内部 ----
    def _tag_search(
        self,
        tags: list[str],
        *,
        match_all: bool,
        allowed: set[str] | None,
    ) -> list[dict[str, Any]]:
        if not tags:
            return []
        rows = self.tags.search(tags, match_all=match_all, limit=self.config.tag_top_k)
        if allowed is None:
            return rows
        filtered = []
        for row in rows:
            faction = str(row["meta"].get("faction", "") or "")
            if not faction or faction in allowed:
                filtered.append(row)
        return filtered

    def index_document(
        self,
        ref: str,
        text: str,
        tags: list[str],
        *,
        faction: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把实体同时写入标签索引与向量库。"""
        meta: dict[str, Any] = {"faction": faction, **(extra or {})}
        tag_result = self.tags.add_tags(ref, tags, meta)
        self.tags.set_faction(ref, faction) if faction else None
        vector_size = self.vectors.upsert(ref, text, meta={**meta, "tags": tags})
        return {"ref": ref, "tags": tag_result["tags"], "vector_size": vector_size}
