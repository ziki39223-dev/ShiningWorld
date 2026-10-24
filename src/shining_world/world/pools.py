"""四大世界观子库 + 变更提案审批队列。

统一约定：
* 任何写操作分两类——「直接写」(种子录入，阶段一) 与「提案后写」(运行期变更)。
* 提案保存在 ``world-bible/proposals.json``，审批通过才落库，并保留修改日志与版本。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..common.errors import ErrorCode, ToolError
from ..common.ids import new_id, now_iso
from ..common.jsonio import read_json, write_json
from ..config.settings import AppSettings
from ..retrieval.engine import RetrievalEngine
from ..retrieval.tag_index import validate_tags
from .character_sheet import (
    build_character_sheet,
    merge_character_patch,
    validate_character_sheet,
)


class _JsonPool:
    """单文件 JSON 池子的通用读写骨架。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        data = read_json(path, default={}) or {}
        self._items: dict[str, dict[str, Any]] = data.get("items", {})

    def _flush(self) -> None:
        self._lock_assert()
        write_json(self.path, {"items": self._items})

    def _lock_assert(self) -> None:
        # 占位：所有调用方都已在 with self._lock 内
        return None

    # ---- 通用 CRUD ----
    def upsert(self, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = dict(payload)
            record["id"] = item_id
            record.setdefault("version", 1)
            record["updated_at"] = now_iso()
            self._items[item_id] = record
            self._flush()
            return record

    def get(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"{self.path.stem} 中不存在：{item_id}",
                    {"pool": self.path.stem, "available": sorted(self._items)[:20]},
                )
            return dict(item)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(v) for v in self._items.values()]

    def delete(self, item_id: str) -> bool:
        with self._lock:
            existed = self._items.pop(item_id, None) is not None
            if existed:
                self._flush()
            return existed

    def count(self) -> int:
        with self._lock:
            return len(self._items)


class PlotPool(_JsonPool):
    """剧情池：主线大纲 + 临时定向事件。"""

    def __init__(self, root: Path, retrieval: RetrievalEngine) -> None:
        super().__init__(root / "plot" / "events.json")
        self.retrieval = retrieval

    def set_mainline_outline(
        self,
        outline: str,
        *,
        timeline: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not outline.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "主线大纲不能为空")
        record = self.upsert(
            "mainline",
            {"kind": "mainline", "outline": outline.strip(), "timeline": list(timeline or [])},
        )
        self.retrieval.index_document(
            "plot:mainline",
            outline.strip(),
            ["plot:主线大纲"],
            faction="",
            extra={"kind": "mainline"},
        )
        return record

    def add_event(
        self,
        title: str,
        content: str,
        *,
        visible_factions: list[str] | None = None,
        active_streams: list[str] | None = None,
        tags: list[str] | None = None,
        ttl_rounds: int = 0,
    ) -> dict[str, Any]:
        if not title.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "事件标题不能为空")
        event_id = new_id("event")
        record = self.upsert(
            event_id,
            {
                "kind": "ad_hoc",
                "title": title.strip(),
                "content": content.strip(),
                "visible_factions": list(visible_factions or []),
                "active_streams": list(active_streams or []),
                "ttl_rounds": int(ttl_rounds),
                "rounds_elapsed": 0,
                "tags": validate_tags(tags or []),
                "created_at": now_iso(),
            },
        )
        self.retrieval.index_document(
            f"event:{event_id}",
            f"{title}\n{content}",
            record["tags"] or ["event:临时事件"],
            faction="",
            extra={
                "kind": "event",
                "visible_factions": record["visible_factions"],
            },
        )
        return record

    def list_events(
        self,
        *,
        faction: str | None = None,
        stream_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = []
        for item in self.list():
            if item.get("kind") != "ad_hoc":
                continue
            visible = item.get("visible_factions") or []
            if faction and visible and faction not in visible:
                continue
            active = item.get("active_streams") or []
            if stream_id and active and stream_id not in active:
                continue
            rows.append(item)
        return rows

    def mainline(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._items["mainline"]) if "mainline" in self._items else None

    def purge_expired(self) -> list[str]:
        """清理 ttl 到期的临时事件，返回被清理 ID。"""
        removed: list[str] = []
        with self._lock:
            for item_id, item in list(self._items.items()):
                if item.get("kind") != "ad_hoc":
                    continue
                ttl = int(item.get("ttl_rounds") or 0)
                if ttl and int(item.get("rounds_elapsed") or 0) >= ttl:
                    self._items.pop(item_id, None)
                    removed.append(item_id)
            if removed:
                self._flush()
        for item_id in removed:
            self.retrieval.vectors.remove(f"event:{item_id}")
        return removed


class MapPool(_JsonPool):
    """地图池：地点、领地、地理规则。"""

    def __init__(self, root: Path, retrieval: RetrievalEngine) -> None:
        super().__init__(root / "map" / "places.json")
        self.retrieval = retrieval

    def upsert_place(
        self,
        name: str,
        *,
        description: str = "",
        faction: str = "",
        rules: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "地点名称不能为空")
        place_id = f"loc:{name.strip()}"
        record = self.upsert(
            place_id,
            {
                "name": name.strip(),
                "description": description.strip(),
                "faction": faction.strip(),
                "rules": list(rules or []),
                "tags": validate_tags(tags or [place_id]),
            },
        )
        self.retrieval.index_document(
            place_id,
            f"{name}\n{description}\n" + "\n".join(rules or []),
            record["tags"],
            faction=faction.strip(),
            extra={"kind": "place"},
        )
        return record

    def list_places(self, *, faction: str = "") -> list[dict[str, Any]]:
        """列出地点；给了 faction 时按归属过滤（空归属视为公共）。"""
        rows = self.list()
        if faction.strip():
            rows = [
                r for r in rows if not r.get("faction") or r.get("faction") == faction.strip()
            ]
        return sorted(rows, key=lambda r: str(r.get("name", "")))

    def get_place(self, name: str) -> dict[str, Any]:
        """按名称读取地点。"""
        return self.get(f"loc:{str(name).strip()}")

    def remove_place(self, name: str) -> dict[str, Any]:
        """删除地点，并从标签索引与向量库撤下。"""
        place_id = f"loc:{str(name).strip()}"
        existed = self.delete(place_id)
        if not existed:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"地点不存在：{name}",
                {"available": [r.get("name") for r in self.list()][:20]},
            )
        self.retrieval.vectors.remove(place_id)
        self.retrieval.tags.remove_ref(place_id)
        return {"place": str(name).strip(), "ref": place_id, "removed": True}


class CulturePool(_JsonPool):
    """人文池：势力、种族、盟约关系。"""

    def __init__(self, root: Path, retrieval: RetrievalEngine) -> None:
        super().__init__(root / "culture" / "factions.json")
        self.retrieval = retrieval

    def upsert_faction(
        self,
        name: str,
        *,
        description: str = "",
        stance: str = "neutral",
        allies: list[str] | None = None,
        enemies: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "势力名称不能为空")
        faction_id = f"faction:{name.strip()}"
        record = self.upsert(
            faction_id,
            {
                "name": name.strip(),
                "description": description.strip(),
                "stance": stance,
                "allies": list(allies or []),
                "enemies": list(enemies or []),
                "tags": validate_tags(tags or [faction_id]),
            },
        )
        self.retrieval.index_document(
            faction_id,
            f"{name}\n{description}\n立场：{stance}\n盟友：{'、'.join(allies or [])}\n敌对：{'、'.join(enemies or [])}",
            record["tags"],
            faction=name.strip(),
            extra={"kind": "faction", "stance": stance},
        )
        return record

    def list_factions(self) -> list[dict[str, Any]]:
        """列出全部势力。"""
        return sorted(self.list(), key=lambda r: str(r.get("name", "")))

    def get_faction(self, name: str) -> dict[str, Any]:
        """按名称读取势力档案。"""
        return self.get(f"faction:{str(name).strip()}")

    def remove_faction(self, name: str) -> dict[str, Any]:
        """删除势力，并从标签索引与向量库撤下。"""
        faction_id = f"faction:{str(name).strip()}"
        existed = self.delete(faction_id)
        if not existed:
            raise ToolError(
                ErrorCode.NOT_FOUND,
                f"势力不存在：{name}",
                {"available": [r.get("name") for r in self.list()][:20]},
            )
        self.retrieval.vectors.remove(faction_id)
        self.retrieval.tags.remove_ref(faction_id)
        return {"faction": str(name).strip(), "ref": faction_id, "removed": True}


class CharacterPool(_JsonPool):
    """人物池：角色卡 + 版本历史 + 查看权限。"""

    def __init__(self, root: Path, retrieval: RetrievalEngine) -> None:
        super().__init__(root / "character" / "characters.json")
        self.retrieval = retrieval

    def approve_card(
        self,
        sheet: dict[str, Any],
        *,
        approved_by: str = "human",
        note: str = "",
    ) -> dict[str, Any]:
        problems = validate_character_sheet(sheet)
        if problems:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                "角色卡校验不通过",
                {"problems": problems},
            )
        char_id = str(sheet.get("char_id") or new_id("char"))
        name = str(sheet.get("name", "") or "").strip()
        with self._lock:
            # 同名角色视为同一实体的新版本，避免重复入库
            if char_id not in self._items and name:
                same_name = next(
                    (cid for cid, rec in self._items.items() if rec.get("name") == name),
                    None,
                )
                if same_name:
                    char_id = same_name
            existing = self._items.get(char_id, {})
            history = list(existing.get("history") or [])
            if existing:
                history.append(
                    {
                        "version": int(existing.get("version", 1)),
                        "sheet": {k: v for k, v in existing.items() if k not in {"history"}},
                        "archived_at": now_iso(),
                    }
                )
            record = dict(sheet)
            record["char_id"] = char_id
            record["approved_by"] = approved_by
            record["approved_at"] = now_iso()
            record["note"] = note
            record["version"] = int(existing.get("version", 0)) + 1
            record["history"] = history[-20:]
            record["updated_at"] = now_iso()
            self._items[char_id] = record
            self._flush()

        name = record.get("name", "")
        tags = validate_tags([f"char:{name}", *record.get("tags", [])])
        record["tags"] = tags
        self.retrieval.index_document(
            f"char:{name}",
            self._render_text(record),
            tags,
            faction=str(record.get("faction", "") or ""),
            extra={"kind": "character", "char_id": char_id, "secret": bool(record.get("secret"))},
        )
        return record

    def get_card(self, name_or_id: str, *, viewer_faction: str = "") -> dict[str, Any]:
        with self._lock:
            record = self._items.get(name_or_id)
            if record is None:
                record = next(
                    (r for r in self._items.values() if r.get("name") == name_or_id),
                    None,
                )
            if record is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"角色不存在：{name_or_id}",
                    {"available": [r.get("name") for r in self._items.values()][:20]},
                )
            record = dict(record)

        secret = str(record.get("secret", "") or "")
        if secret and viewer_faction not in (record.get("secret_visible_to") or []):
            record["secret"] = "【受控保密：当前阵营无查看权限】"
            record["secret_redacted"] = True
        else:
            record["secret_redacted"] = False
        record.pop("history", None)
        return record

    def rollback(self, name_or_id: str, version: int) -> dict[str, Any]:
        with self._lock:
            record = self._items.get(name_or_id)
            if record is None:
                record = next((r for r in self._items.values() if r.get("name") == name_or_id), None)
            if record is None:
                raise ToolError(ErrorCode.NOT_FOUND, f"角色不存在：{name_or_id}")
            target = next(
                (h for h in record.get("history") or [] if int(h.get("version", 0)) == version),
                None,
            )
            if target is None:
                raise ToolError(
                    ErrorCode.NOT_FOUND,
                    f"未找到版本 {version}",
                    {"versions": [h.get("version") for h in record.get("history") or []]},
                )
            restored = dict(target["sheet"])
            restored["char_id"] = record["char_id"]
            restored["history"] = record.get("history") or []
            restored["version"] = version
            restored["updated_at"] = now_iso()
            restored["note"] = f"回滚到版本 {version}"
            self._items[restored["char_id"]] = restored
            self._flush()
        return self.get_card(restored["char_id"])

    @staticmethod
    def _render_text(record: dict[str, Any]) -> str:
        traits = record.get("traits") or {}
        bonds = "、".join(
            f"{b.get('target')}({b.get('relation')})" for b in record.get("bond", [])
        )
        parts = [
            f"姓名：{record.get('name', '')}",
            f"身份：{record.get('identity', '')}",
            f"核心信念：{record.get('core_belief', '')}",
            f"稳定性格：{'、'.join(traits.get('stable', []))}",
            f"临时情绪：{'、'.join(traits.get('temporary', []))}",
            f"说话风格：{record.get('speech_style', '')}",
            f"硬性规则：{'、'.join(record.get('hard_rule', []))}",
            f"关系：{bonds}",
        ]
        return "\n".join(p for p in parts if p.split("：", 1)[1].strip())


class ProposalQueue:
    """变更提案队列：世界观修改必须走提案 + 人工审批。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        data = read_json(path, default={}) or {}
        self._items: dict[str, dict[str, Any]] = data.get("items", {})

    def _flush(self) -> None:
        write_json(self.path, {"items": self._items})

    def submit(
        self,
        *,
        target: str,
        action: str,
        payload: dict[str, Any],
        reason: str = "",
        submitted_by: str = "system",
    ) -> dict[str, Any]:
        """提交提案；target 形如 ``character / map / culture / plot``。"""
        proposal_id = new_id("prop")
        record = {
            "proposal_id": proposal_id,
            "target": target,
            "action": action,
            "payload": payload,
            "reason": reason,
            "submitted_by": submitted_by,
            "submitted_at": now_iso(),
            "status": "pending",
        }
        with self._lock:
            self._items[proposal_id] = record
            self._flush()
        return record

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            rows = list(self._items.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return sorted(rows, key=lambda r: r.get("submitted_at", ""), reverse=True)

    def get(self, proposal_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._items.get(proposal_id)
            if row is None:
                raise ToolError(ErrorCode.NOT_FOUND, f"提案不存在：{proposal_id}")
            return dict(row)

    def mark(self, proposal_id: str, status: str, *, note: str = "") -> dict[str, Any]:
        with self._lock:
            row = self._items.get(proposal_id)
            if row is None:
                raise ToolError(ErrorCode.NOT_FOUND, f"提案不存在：{proposal_id}")
            row["status"] = status
            row["decided_at"] = now_iso()
            row["decision_note"] = note
            self._flush()
            return dict(row)


class WorldBible:
    """四大子库 + 提案队列的门面。"""

    def __init__(self, settings: AppSettings, retrieval: RetrievalEngine) -> None:
        self.settings = settings
        self.retrieval = retrieval
        root = settings.world_dir
        self.plot = PlotPool(root, retrieval)
        self.map = MapPool(root, retrieval)
        self.culture = CulturePool(root, retrieval)
        self.character = CharacterPool(root, retrieval)
        self.proposals = ProposalQueue(settings.proposals_path)

    def stats(self) -> dict[str, Any]:
        return {
            "plot_events": self.plot.count(),
            "places": self.map.count(),
            "factions": self.culture.count(),
            "characters": self.character.count(),
            "pending_proposals": len(self.proposals.list("pending")),
            "vector_rows": self.retrieval.vectors.count(),
            "tags": len(self.retrieval.tags.all_tags()),
        }

    def approve_proposal(self, proposal_id: str, *, approved: bool = True, note: str = "") -> dict[str, Any]:
        """审批提案：通过则按 target 落库，失败则回滚状态并抛出。"""
        proposal = self.proposals.get(proposal_id)
        if proposal["status"] != "pending":
            raise ToolError(
                ErrorCode.CONFLICT,
                f"提案已处理：{proposal['status']}",
                {"proposal_id": proposal_id},
            )
        if not approved:
            return self.proposals.mark(proposal_id, "rejected", note=note)

        target = proposal["target"]
        payload = proposal.get("payload") or {}
        action = proposal.get("action", "upsert")

        try:
            if target == "character":
                # 同名角色已存在时一律按补丁合并，避免 create 覆盖掉已有 hard_rule
                if action == "patch" or self._character_exists(payload.get("name", "")):
                    result = self._apply_character_patch(payload, note=note)
                else:
                    result = self.character.approve_card(build_character_sheet(payload), note=note)
            elif target == "map":
                result = self.map.upsert_place(
                    payload.get("name", ""),
                    description=payload.get("description", ""),
                    faction=payload.get("faction", ""),
                    rules=payload.get("rules"),
                    tags=payload.get("tags"),
                )
            elif target == "culture":
                result = self.culture.upsert_faction(
                    payload.get("name", ""),
                    description=payload.get("description", ""),
                    stance=payload.get("stance", "neutral"),
                    allies=payload.get("allies"),
                    enemies=payload.get("enemies"),
                    tags=payload.get("tags"),
                )
            elif target == "plot":
                result = self.plot.add_event(
                    payload.get("title", ""),
                    payload.get("content", ""),
                    visible_factions=payload.get("visible_factions"),
                    active_streams=payload.get("active_streams"),
                    tags=payload.get("tags"),
                    ttl_rounds=int(payload.get("ttl_rounds") or 0),
                )
            else:
                raise ToolError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"未知提案目标：{target}",
                    {"allowed": ["character", "map", "culture", "plot"]},
                )
        except ToolError as exc:
            self.proposals.mark(proposal_id, "failed", note=f"{exc.code}: {exc.message}")
            raise

        marked = self.proposals.mark(proposal_id, "approved", note=note)
        return {"proposal": marked, "applied": result}

    def _character_exists(self, name: str) -> bool:
        """按名称判断角色卡是否已入库。"""
        name = str(name or "").strip()
        if not name:
            return False
        return any(rec.get("name") == name for rec in self.character.list())

    def _apply_character_patch(self, payload: dict[str, Any], *, note: str = "") -> dict[str, Any]:
        """把蒸馏补丁合并进已有角色卡后再归档（只增不减 stable / hard_rule）。"""
        name = str(payload.get("name", "") or "").strip()
        if not name:
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "角色补丁缺少 name")
        base = self.character.get_card(name)
        merged = merge_character_patch(base, payload, source="distill-approval", note=note)
        merged.pop("secret_redacted", None)
        return self.character.approve_card(build_character_sheet(merged, source="distill"), note=note)

    def apply_patch_to_character(self, patch: dict[str, Any]) -> dict[str, Any]:
        """提交角色补丁提案（不直接改库，等人工审批）。"""
        if not isinstance(patch, dict) or not patch:
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "角色补丁不能为空")
        return self.proposals.submit(
            target="character",
            action="patch" if patch.get("name") else "create",
            payload=patch,
            reason="角色蒸馏结果待审",
            submitted_by="distiller",
        )


def build_world_bible(settings: AppSettings, retrieval: RetrievalEngine) -> WorldBible:
    return WorldBible(settings, retrieval)
