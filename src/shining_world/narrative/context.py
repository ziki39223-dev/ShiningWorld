"""上下文拼装：主线约束 + 角色卡 + 地点规则 + 生效事件 + 最新快照 + 近期对话。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..retrieval.engine import RetrievalEngine
from ..streams.manager import StreamManager
from ..streams.snapshot import SnapshotManager
from ..world.pools import WorldBible


@dataclass
class NarrativeContext:
    """一次生成的上下文快照（同时可作为审计记录）。"""

    stream_id: str
    stream_name: str
    faction: str
    perspective: str
    characters: list[dict[str, Any]] = field(default_factory=list)
    places: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    retrieval_strategy: str = "empty"
    retrieval_hits: list[dict[str, Any]] = field(default_factory=list)
    snapshot_context: str = ""
    recent_context: str = ""

    def to_prompt_block(self, *, mainline: str = "") -> str:
        """渲染成给模型看的纯文本块（含标签，便于 Mock 与审计）。"""
        lines: list[str] = []
        if mainline:
            lines.append(f"主线约束：{mainline}")
        lines.append(f"支线名称：{self.stream_name}")
        if self.faction:
            lines.append(f"阵营：{self.faction}")
        if self.perspective:
            lines.append(f"视角：{self.perspective}")

        if self.characters:
            lines.append("出场角色：")
            for sheet in self.characters:
                traits = sheet.get("traits") or {}
                lines.append(
                    "  - {name}（{identity}）：core={belief}；stable={stable}；speech={speech}；hard_rule={rules}".format(
                        name=sheet.get("name", ""),
                        identity=sheet.get("identity", ""),
                        belief=sheet.get("core_belief", ""),
                        stable="、".join(traits.get("stable", [])) or "无",
                        speech=sheet.get("speech_style", "") or "无",
                        rules="、".join(sheet.get("hard_rule", [])) or "无",
                    )
                )
        if self.places:
            lines.append("地点规则：")
            for place in self.places:
                rules = "、".join(place.get("rules", [])) or "无特殊规则"
                lines.append(f"  - {place.get('name', '')}：{rules}")
        if self.events:
            lines.append("生效事件：")
            for event in self.events:
                lines.append(f"  - {event.get('title', '')}：{event.get('content', '')}")
        if self.snapshot_context:
            lines.append("历史快照：")
            lines.append(self.snapshot_context)
        if self.recent_context:
            lines.append("近期剧情（供衔接，不要复述）：")
            lines.append(self.recent_context)
        return "\n".join(lines)

    def to_public(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "stream_name": self.stream_name,
            "faction": self.faction,
            "perspective": self.perspective,
            "characters": [c.get("name") for c in self.characters],
            "places": [p.get("name") for p in self.places],
            "events": [e.get("title") for e in self.events],
            "retrieval_strategy": self.retrieval_strategy,
            "retrieval_hits": len(self.retrieval_hits),
            "has_snapshot_context": bool(self.snapshot_context),
            "has_recent_context": bool(self.recent_context),
        }


class ContextBuilder:
    """按支线拼装生成上下文。"""

    def __init__(
        self,
        world: WorldBible,
        streams: StreamManager,
        snapshots: SnapshotManager,
        retrieval: RetrievalEngine,
    ) -> None:
        self.world = world
        self.streams = streams
        self.snapshots = snapshots
        self.retrieval = retrieval

    def build(
        self,
        stream_id: str,
        *,
        extra_tags: list[str] | None = None,
        query: str = "",
        max_characters: int = 3,
    ) -> NarrativeContext:
        record = self.streams.get(stream_id)
        tags = [f"faction:{record.faction}"] if record.faction else []
        tags.extend(record.tags)
        tags.extend(extra_tags or [])

        memory = self.snapshots.build_memory_context(stream_id)
        search_query = query or memory.get("recent_context", "")[-600:] or record.name
        found = self.retrieval.search(
            tags,
            search_query,
            faction_scope={record.faction} if record.faction else None,
            match_all=False,
        )

        characters: list[dict[str, Any]] = []
        places: list[dict[str, Any]] = []
        for hit in found["hits"]:
            ref = hit["ref"]
            if ref.startswith("char:") and len(characters) < max_characters:
                try:
                    card = self.world.character.get_card(
                        ref.split(":", 1)[1],
                        viewer_faction=record.faction,
                    )
                except Exception:  # noqa: BLE001 - 索引里可能残留旧条目
                    continue
                characters.append(card)
            elif ref.startswith("loc:") and len(places) < 2:
                try:
                    places.append(self.world.map.get(ref))
                except Exception:  # noqa: BLE001
                    continue

        events = self.world.plot.list_events(faction=record.faction or None, stream_id=record.stream_id)

        return NarrativeContext(
            stream_id=record.stream_id,
            stream_name=record.name,
            faction=record.faction,
            perspective=record.perspective,
            characters=characters,
            places=places,
            events=events[:4],
            retrieval_strategy=found["strategy"],
            retrieval_hits=found["hits"],
            snapshot_context=memory.get("snapshot_context", ""),
            recent_context=memory.get("recent_context", ""),
        )
