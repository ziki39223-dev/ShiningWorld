"""标签索引：全局 tag → 实体引用 的精确检索表。

标签规范（与文档一致）：
    char:角色名 / loc:地点名 / faction:势力 / event:事件ID / plot:剧情段落 / rule:世界观规则
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from ..common.errors import ErrorCode, ToolError
from ..common.jsonio import read_json, write_json

TAG_PREFIXES = ("char", "loc", "faction", "event", "plot", "rule")
_TAG_RE = re.compile(r"^[a-z]+:[^\s:]{1,64}$")


def validate_tags(tags: list[str]) -> list[str]:
    """校验标签格式，返回去重后的列表；非法标签抛错。"""
    cleaned: list[str] = []
    for tag in tags:
        text = str(tag).strip()
        if not text:
            continue
        if not _TAG_RE.match(text):
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"标签格式非法：{text}",
                {"expect": "char:名字 / loc:地点 / faction:势力 / event:事件ID / plot:段落 / rule:规则"},
            )
        if text.split(":", 1)[0] not in TAG_PREFIXES:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                f"标签前缀非法：{text}",
                {"allowed": list(TAG_PREFIXES)},
            )
        if text not in cleaned:
            cleaned.append(text)
    return cleaned


class TagIndex:
    """持久化的倒排索引：``{tags: {tag: [ref, ...]}, refs: {ref: {tags, kind, faction, title}}}``。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = read_json(path, default={}) or {}
        self._data.setdefault("tags", {})
        self._data.setdefault("refs", {})

    # ---- 持久化 ----
    def save(self) -> None:
        with self._lock:
            write_json(self.path, self._data)

    # ---- 写入 ----
    def add_tags(self, ref: str, tags: list[str], meta: dict[str, Any] | None = None) -> dict[str, Any]:
        tags = validate_tags(tags)
        with self._lock:
            entry = self._data["refs"].setdefault(ref, {"tags": [], "meta": {}})
            for tag in tags:
                if tag not in entry["tags"]:
                    entry["tags"].append(tag)
                refs = self._data["tags"].setdefault(tag, [])
                if ref not in refs:
                    refs.append(ref)
            if meta:
                entry["meta"].update(meta)
            entry["meta"].setdefault("ref", ref)
        return {"ref": ref, "tags": list(entry["tags"])}

    def remove_tags(self, ref: str, tags: list[str]) -> dict[str, Any]:
        with self._lock:
            entry = self._data["refs"].get(ref)
            if entry is None:
                raise ToolError(ErrorCode.NOT_FOUND, f"实体无标签记录：{ref}", {"ref": ref})
            removed: list[str] = []
            for tag in tags:
                if tag in entry["tags"]:
                    entry["tags"].remove(tag)
                    removed.append(tag)
                refs = self._data["tags"].get(tag, [])
                if ref in refs:
                    refs.remove(ref)
                if not refs:
                    self._data["tags"].pop(tag, None)
            if not entry["tags"]:
                self._data["refs"].pop(ref, None)
        return {"ref": ref, "removed": removed, "tags": entry["tags"]}

    def set_faction(self, ref: str, faction: str) -> None:
        with self._lock:
            entry = self._data["refs"].setdefault(ref, {"tags": [], "meta": {}})
            entry["meta"]["faction"] = faction

    # ---- 查询 ----
    def tags_of(self, ref: str) -> list[str]:
        with self._lock:
            return list(self._data["refs"].get(ref, {}).get("tags", []))

    def meta_of(self, ref: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data["refs"].get(ref, {}).get("meta", {}))

    def search(
        self,
        tags: list[str],
        *,
        match_all: bool = True,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """标签检索：match_all=True 为交集，否则并集。"""
        wanted = validate_tags(tags)
        if not wanted:
            return []
        with self._lock:
            sets = [set(self._data["tags"].get(tag, [])) for tag in wanted]
            if not sets:
                return []
            if match_all:
                refs = set.intersection(*sets) if all(sets) else set()
            else:
                refs = set().union(*sets)
            rows = []
            for ref in refs:
                entry = self._data["refs"].get(ref, {})
                rows.append(
                    {
                        "ref": ref,
                        "tags": list(entry.get("tags", [])),
                        "meta": dict(entry.get("meta", {})),
                    }
                )
        rows.sort(key=lambda r: (-len(set(r["tags"]) & set(wanted)), r["ref"]))
        return rows[:limit]

    def remove_ref(self, ref: str) -> dict[str, Any]:
        """整条实体下线：清空它所有标签的反向引用。"""
        with self._lock:
            entry = self._data["refs"].get(ref)
            if entry is None:
                return {"ref": ref, "removed": False}
            tags = list(entry.get("tags", []))
            for tag in tags:
                refs = self._data["tags"].get(tag, [])
                if ref in refs:
                    refs.remove(ref)
                if not refs:
                    self._data["tags"].pop(tag, None)
            self._data["refs"].pop(ref, None)
        return {"ref": ref, "removed_tags": tags, "removed": True}

    def all_tags(self) -> dict[str, int]:
        with self._lock:
            return {tag: len(refs) for tag, refs in sorted(self._data["tags"].items())}

    def all_refs(self, limit: int = 200) -> list[dict[str, Any]]:
        """列出全部实体引用（阵营隔离过滤时用）。"""
        with self._lock:
            rows = [
                {"ref": ref, "tags": list(entry.get("tags", [])), "meta": dict(entry.get("meta", {}))}
                for ref, entry in self._data["refs"].items()
            ]
        rows.sort(key=lambda r: r["ref"])
        return rows[:limit]
