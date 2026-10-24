"""工具门面：所有 MCP 工具的实现体。

约定：
* 每个方法返回 ``{"ok": True, ...}`` 或 ``{"ok": False, "error": {...}}``；
* 业务异常统一由 ``@envelope`` 捕获成信封，绝不向客户端抛裸异常。
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from ..common.errors import ErrorCode, ToolError, fail, ok
from ..common.text import estimate_tokens
from ..config.settings import ProviderConfig
from ..retrieval.tag_index import validate_tags
from ..streams.manager import StreamRecord
from ..tools.bootstrap import ShiningWorldService, persist_indexes
from ..world.character_sheet import build_character_sheet
from ..world.pools import WorldBible

_log = logging.getLogger("shining_world.facade")


def envelope(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """捕获 ToolError / 未知异常，转成统一信封。"""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except ToolError as exc:
            _log.warning("%s 失败：%s %s", func.__name__, exc.code, exc.message)
            return fail(exc)
        except Exception as exc:  # noqa: BLE001 - 工具层是最后一道防线
            _log.exception("%s 未捕获异常", func.__name__)
            return fail(
                ToolError(
                    ErrorCode.INTERNAL,
                    f"{func.__name__} 内部错误：{exc}",
                    {"type": type(exc).__name__},
                )
            )

    return wrapper


def _stream_row(record: StreamRecord) -> dict[str, Any]:
    return record.to_public()


class ToolFacade:
    """把 ShiningWorldService 暴露成一组稳定的工具方法。"""

    def __init__(self, service: ShiningWorldService) -> None:
        self.service = service

    # ============ 系统 ============
    @envelope
    def get_service_status(self) -> dict[str, Any]:
        """查看服务整体状态（工作区、支线数、世界观统计、默认服务商）。"""
        stats = self.service.stats()
        return ok(
            **stats,
            default_provider=self.service.manager.default_name(),
            pending_proposals=len(self.service.world.proposals.list("pending")),
        )

    # ============ 5.1 模型服务商管理 ============
    @envelope
    def list_providers(self) -> dict[str, Any]:
        """列出全部 API 服务商（含付费与免费池）及其运行时状态。"""
        rows = self.service.manager.list_public()
        return ok(
            default_provider=self.service.manager.default_name(),
            count=len(rows),
            providers=rows,
        )

    @envelope
    def switch_default_provider(self, name: str) -> dict[str, Any]:
        """切换全局默认模型源。"""
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "name 不能为空")
        switched = self.service.manager.switch_default(name.strip())
        return ok(default_provider=switched)

    @envelope
    def set_provider_quota(
        self,
        name: str,
        max_concurrency: int | None = None,
        rpm: int | None = None,
    ) -> dict[str, Any]:
        """设置单服务商的并发与每分钟请求上限。"""
        if max_concurrency is None and rpm is None:
            raise ToolError(
                ErrorCode.INVALID_ARGUMENT,
                "max_concurrency 与 rpm 至少提供一个",
            )
        config = self.service.manager.set_quota(
            name.strip(),
            max_concurrency=max_concurrency,
            rpm=rpm,
        )
        return ok(provider=config.to_public())

    @envelope
    def test_provider_connection(self, name: str | None = None) -> dict[str, Any]:
        """连通性测试；不传 name 则测全部服务商。"""
        result = self.service.manager.test_connection(name.strip() if name else None)
        return ok(**result)

    # ============ 5.2 叙事流管理器 ============
    @envelope
    def create_narrative_stream(
        self,
        name: str,
        faction: str = "",
        perspective: str = "",
        cooldown_s: int | None = None,
        tags: list[str] | None = None,
        cell: int = 0,
    ) -> dict[str, Any]:
        """创建新支线（视角、阵营、冷却时长、标签、九宫格位置）。"""
        record = self.service.streams.create(
            name,
            faction=faction,
            perspective=perspective,
            cooldown_s=cooldown_s,
            tags=validate_tags(tags or []),
            cell=cell,
        )
        return ok(stream=_stream_row(record))

    @envelope
    def trigger_stream_step(
        self,
        stream_id: str,
        hint: str = "",
        dry_run: bool = False,
        max_tokens: int = 700,
    ) -> dict[str, Any]:
        """手动步进指定支线：拼装上下文 → 调模型 → 校验 → 落盘。"""
        result = self.service.engine.step(
            stream_id.strip(),
            hint=hint,
            dry_run=dry_run,
            max_tokens=int(max_tokens),
        )
        return ok(result=result.to_public())

    @envelope
    def step_all_due_streams(self, limit: int = 9) -> dict[str, Any]:
        """把所有冷却结束的支线各推进一步（九宫格卡片轮询刷新用）。"""
        results = self.service.engine.step_all_due(limit=int(limit))
        succeeded = sum(1 for r in results if r.get("ok"))
        return ok(
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            results=results,
        )

    @envelope
    def get_stream_content(
        self,
        stream_id: str,
        since_chars: int = 0,
        limit_chars: int = 4000,
    ) -> dict[str, Any]:
        """读取支线增量文本（DSH 卡片实时展示）。"""
        return ok(
            **self.service.streams.read_content(
                stream_id.strip(),
                since_chars=int(since_chars),
                limit_chars=int(limit_chars),
            )
        )

    @envelope
    def list_all_streams(self) -> dict[str, Any]:
        """查看全部支线状态。"""
        rows = [_stream_row(record) for record in self.service.streams.list()]
        return ok(
            count=len(rows),
            running=[r for r in rows if r["status"] == "running"],
            streams=rows,
        )

    @envelope
    def pause_stream(self, stream_id: str) -> dict[str, Any]:
        """暂停单支线（该支线计时器冻结）。"""
        return ok(stream=_stream_row(self.service.streams.pause(stream_id.strip())))

    @envelope
    def resume_stream(self, stream_id: str) -> dict[str, Any]:
        """恢复单支线。"""
        return ok(stream=_stream_row(self.service.streams.resume(stream_id.strip())))

    @envelope
    def pause_all_streams(self) -> dict[str, Any]:
        """全局冻结：暂停所有支线。"""
        records = self.service.streams.pause_all()
        return ok(count=len(records), streams=[_stream_row(r) for r in records])

    @envelope
    def resume_all_streams(self) -> dict[str, Any]:
        """全局继续：恢复所有支线。"""
        records = self.service.streams.resume_all()
        return ok(count=len(records), streams=[_stream_row(r) for r in records])

    # ============ 5.3 检索引擎 ============
    @envelope
    def add_tags(
        self,
        ref: str,
        tags: list[str],
        text: str = "",
        faction: str = "",
    ) -> dict[str, Any]:
        """给实体批量打标签；提供 text 时同步写入向量库。"""
        ref = ref.strip()
        if not ref:
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "ref 不能为空")
        result = self.service.retrieval.index_document(
            ref,
            text or ref,
            validate_tags(tags),
            faction=faction.strip(),
            extra={"kind": ref.split(":", 1)[0]},
        )
        persist_indexes(self.service)
        return ok(**result)

    @envelope
    def remove_tags(self, ref: str, tags: list[str]) -> dict[str, Any]:
        """删除指定标签（清空后实体从索引移除）。"""
        result = self.service.retrieval.tags.remove_tags(ref.strip(), validate_tags(tags))
        persist_indexes(self.service)
        return ok(**result)

    @envelope
    def search_by_tags(
        self,
        tags: list[str],
        match_all: bool = True,
        faction: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """纯标签精确检索（优先执行，不走向量）。"""
        wanted = validate_tags(tags)
        if not wanted:
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "tags 不能为空")
        rows = self.service.retrieval.tags.search(wanted, match_all=match_all, limit=int(limit))
        if faction.strip():
            rows = [
                r
                for r in rows
                if not r["meta"].get("faction") or r["meta"].get("faction") == faction.strip()
            ]
        return ok(strategy="tag", count=len(rows), hits=rows)

    @envelope
    def vector_search(
        self,
        query: str,
        top_k: int = 6,
        faction: str = "",
    ) -> dict[str, Any]:
        """语义向量召回（标签命中不足时兜底）。"""
        if not query.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "query 不能为空")
        hits = self.service.retrieval.vectors.search(
            query.strip(),
            top_k=int(top_k),
            allowed_factions={faction.strip()} if faction.strip() else None,
        )
        return ok(strategy="vector", count=len(hits), hits=hits)

    @envelope
    def filter_by_faction(self, faction: str, refs: list[str] | None = None) -> dict[str, Any]:
        """按阵营权限过滤内容，实现信息隔离。"""
        faction = faction.strip()
        if not faction:
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "faction 不能为空")
        visible: list[dict[str, Any]] = []
        hidden: list[dict[str, Any]] = []
        if refs:
            candidates = [
                {
                    "ref": ref,
                    "meta": self.service.retrieval.tags.meta_of(ref),
                    "tags": self.service.retrieval.tags.tags_of(ref),
                }
                for ref in refs
            ]
        else:
            candidates = self.service.retrieval.tags.all_refs()
        for row in candidates:
            owner = str(row["meta"].get("faction", "") or "")
            item = {"ref": row["ref"], "faction": owner, "tags": row["tags"]}
            (hidden if owner and owner != faction else visible).append(item)
        return ok(faction=faction, visible=visible, hidden=hidden)

    # ============ 5.4 世界观池子 ============
    @envelope
    def set_mainline_outline(
        self,
        outline: str,
        timeline: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """录入主线大纲与时序约束。"""
        record = self.service.world.plot.set_mainline_outline(outline, timeline=timeline)
        persist_indexes(self.service)
        return ok(mainline=record)

    @envelope
    def add_ad_hoc_event(
        self,
        title: str,
        content: str,
        visible_factions: list[str] | None = None,
        active_streams: list[str] | None = None,
        tags: list[str] | None = None,
        ttl_rounds: int = 0,
        require_approval: bool = True,
    ) -> dict[str, Any]:
        """插入临时定向事件。

        require_approval=True 时只生成提案，需人工审批后入库（默认）；
        False 时直接入库（用于初始化批量录入）。
        """
        if require_approval:
            proposal = self.service.world.proposals.submit(
                target="plot",
                action="add_event",
                payload={
                    "title": title,
                    "content": content,
                    "visible_factions": list(visible_factions or []),
                    "active_streams": list(active_streams or []),
                    "tags": list(tags or []),
                    "ttl_rounds": int(ttl_rounds),
                },
                reason="临时事件待审",
                submitted_by="system",
            )
            return ok(status="pending_approval", proposal=proposal)

        record = self.service.world.plot.add_event(
            title,
            content,
            visible_factions=visible_factions,
            active_streams=active_streams,
            tags=tags,
            ttl_rounds=ttl_rounds,
        )
        persist_indexes(self.service)
        return ok(status="created", event=record)

    @envelope
    def list_events(
        self,
        faction: str = "",
        stream_id: str = "",
    ) -> dict[str, Any]:
        """查询临时事件（可按阵营 / 支线过滤）。"""
        rows = self.service.world.plot.list_events(
            faction=faction.strip() or None,
            stream_id=stream_id.strip() or None,
        )
        return ok(count=len(rows), events=rows)

    @envelope
    def remove_event(self, event_id: str) -> dict[str, Any]:
        """删除临时事件。"""
        removed = self.service.world.plot.delete(event_id.strip())
        if not removed:
            raise ToolError(ErrorCode.NOT_FOUND, f"事件不存在：{event_id}")
        self.service.retrieval.vectors.remove(f"event:{event_id.strip()}")
        persist_indexes(self.service)
        return ok(event_id=event_id, removed=True)

    @envelope
    def distill_chat_to_character_sheet(
        self,
        character_name: str,
        dialogue: str,
        base_character: str = "",
        auto_submit: bool = True,
    ) -> dict[str, Any]:
        """对话日志自动蒸馏生成角色卡初稿（默认提交审批，不直接入库）。"""
        base_sheet = None
        if base_character.strip():
            base_sheet = self.service.world.character.get_card(base_character.strip())

        result = self.service.distiller.distill(
            character_name.strip(),
            dialogue,
            base_sheet=base_sheet,
        )
        proposal = None
        if auto_submit:
            proposal = self.service.world.proposals.submit(
                target="character",
                action="patch" if base_sheet else "create",
                payload=result["merged_preview"] or result["patch"],
                reason="角色蒸馏结果待审",
                submitted_by="distiller",
            )
        return ok(
            character=result["character"],
            patch=result["patch"],
            merged_preview=result["merged_preview"],
            provider=result["provider"],
            model=result["model"],
            dialogue_tokens=result["dialogue_tokens"],
            proposal=proposal,
        )

    @envelope
    def approve_character_card(
        self,
        sheet: dict[str, Any],
        note: str = "",
        approved_by: str = "human",
    ) -> dict[str, Any]:
        """人工审核并归档角色卡（生成新版本）。"""
        record = self.service.world.character.approve_card(
            build_character_sheet(sheet, source="manual"),
            approved_by=approved_by,
            note=note,
        )
        persist_indexes(self.service)
        return ok(character=_public_character(record))

    @envelope
    def get_character(self, name_or_id: str, viewer_faction: str = "") -> dict[str, Any]:
        """按查看阵营权限读取角色资料（secret 受控）。"""
        record = self.service.world.character.get_card(
            name_or_id.strip(),
            viewer_faction=viewer_faction.strip(),
        )
        return ok(character=_public_character(record))

    @envelope
    def rollback_character(self, name_or_id: str, version: int) -> dict[str, Any]:
        """角色卡版本回滚。"""
        record = self.service.world.character.rollback(name_or_id.strip(), int(version))
        persist_indexes(self.service)
        return ok(character=_public_character(record))

    @envelope
    def upsert_place(
        self,
        name: str,
        description: str = "",
        faction: str = "",
        rules: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """录入/更新地图池地点（初始化直接写，运行期请走提案）。"""
        record = self.service.world.map.upsert_place(
            name,
            description=description,
            faction=faction,
            rules=rules,
            tags=tags,
        )
        persist_indexes(self.service)
        return ok(place=record)

    @envelope
    def upsert_faction(
        self,
        name: str,
        description: str = "",
        stance: str = "neutral",
        allies: list[str] | None = None,
        enemies: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """录入/更新人文池势力。"""
        record = self.service.world.culture.upsert_faction(
            name,
            description=description,
            stance=stance,
            allies=allies,
            enemies=enemies,
            tags=tags,
        )
        persist_indexes(self.service)
        return ok(faction=record)

    @envelope
    def list_places(self, faction: str = "") -> dict[str, Any]:
        """列出地图池地点（可按归属阵营过滤，空归属视为公共）。"""
        rows = self.service.world.map.list_places(faction=faction)
        return ok(count=len(rows), faction=faction, places=rows)

    @envelope
    def get_place(self, name: str) -> dict[str, Any]:
        """按名称读取单个地点档案。"""
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "name 不能为空")
        return ok(place=self.service.world.map.get_place(name))

    @envelope
    def remove_place(self, name: str) -> dict[str, Any]:
        """删除地点，并同步撤下标签索引与向量库条目。"""
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "name 不能为空")
        result = self.service.world.map.remove_place(name)
        persist_indexes(self.service)
        return ok(**result)

    @envelope
    def list_factions(self) -> dict[str, Any]:
        """列出人文池全部势力。"""
        rows = self.service.world.culture.list_factions()
        return ok(count=len(rows), factions=rows)

    @envelope
    def get_faction(self, name: str) -> dict[str, Any]:
        """按名称读取单个势力档案。"""
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "name 不能为空")
        return ok(faction=self.service.world.culture.get_faction(name))

    @envelope
    def remove_faction(self, name: str) -> dict[str, Any]:
        """删除势力，并同步撤下标签索引与向量库条目。"""
        if not name.strip():
            raise ToolError(ErrorCode.INVALID_ARGUMENT, "name 不能为空")
        result = self.service.world.culture.remove_faction(name)
        persist_indexes(self.service)
        return ok(**result)

    # ============ 提案审批 ============
    @envelope
    def list_pending_proposals(self, status: str = "pending") -> dict[str, Any]:
        """查看提案队列（世界观变更 / 角色蒸馏 / 快照）。"""
        rows = self.service.world.proposals.list(status.strip() or None)
        return ok(status=status, count=len(rows), proposals=rows)

    @envelope
    def decide_proposal(self, proposal_id: str, approved: bool = True, note: str = "") -> dict[str, Any]:
        """审批提案：通过即落库，驳回只留记录。"""
        result = self.service.world.approve_proposal(
            proposal_id.strip(),
            approved=approved,
            note=note,
        )
        persist_indexes(self.service)
        return ok(**result)

    # ============ 5.5 快照记忆 ============
    @envelope
    def create_stream_snapshot(
        self,
        stream_id: str,
        summary: str = "",
        key_facts: list[str] | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        """生成记忆快照提案；不传 summary 则自动用模型压缩。"""
        stream_id = stream_id.strip()
        if summary.strip():
            result = self.service.snapshots.create_proposal(
                stream_id,
                summary=summary,
                key_facts=key_facts,
                source=source,
            )
        else:
            result = self.service.engine.propose_snapshot(stream_id)
        return ok(**result)

    @envelope
    def approve_snapshot(self, stream_id: str, snapshot_id: str, note: str = "") -> dict[str, Any]:
        """人工审核快照：归档并返回上下文裁剪范围。"""
        result = self.service.snapshots.approve(stream_id.strip(), snapshot_id.strip(), note=note)
        return ok(**result)

    @envelope
    def list_snapshots(self, stream_id: str) -> dict[str, Any]:
        """列出支线的全部快照。"""
        rows = self.service.snapshots.list_snapshots(stream_id.strip())
        return ok(stream_id=stream_id, count=len(rows), snapshots=rows)

    @envelope
    def purge_stale_events(self) -> dict[str, Any]:
        """清理过期临时事件，控制上下文长度。"""
        removed = self.service.world.plot.purge_expired()
        persist_indexes(self.service)
        return ok(removed=removed, count=len(removed))

    # ============ 5.6 一致性校验 ============
    @envelope
    def check_character_ooc(self, character: str, text: str, viewer_faction: str = "") -> dict[str, Any]:
        """校验角色行为是否突破 hard_rule 底线。"""
        sheet = self.service.world.character.get_card(character.strip(), viewer_faction=viewer_faction)
        violations = self.service.checker.check_character_ooc(sheet, text)
        return ok(
            passed=not any(v.severity == "blocking" for v in violations),
            count=len(violations),
            violations=[v.to_public() for v in violations],
        )

    @envelope
    def check_timeline_conflict(self, text: str, current_day: int = 0) -> dict[str, Any]:
        """检测时序矛盾。"""
        violations = self.service.checker.check_timeline(text, current_day=int(current_day))
        return ok(
            passed=not violations,
            count=len(violations),
            violations=[v.to_public() for v in violations],
        )

    @envelope
    def check_world_rule_conflict(self, text: str, place: str = "") -> dict[str, Any]:
        """跨世界观池子设定冲突检测。"""
        violations = self.service.checker.check_world_rules(text, place=place.strip())
        return ok(
            passed=not violations,
            count=len(violations),
            violations=[v.to_public() for v in violations],
        )

    @envelope
    def pause_stream_on_error(self, stream_id: str, reason: str = "") -> dict[str, Any]:
        """校验失败时冻结指定支线，仅告警不打断其他支线。"""
        record = self.service.streams.set_status(
            stream_id.strip(),
            "error",
            error=reason.strip() or "一致性校验失败",
        )
        return ok(stream=_stream_row(record), affected_others=[])


def _public_character(record: dict[str, Any]) -> dict[str, Any]:
    """对外角色卡：剔除版本历史等内部字段。"""
    hidden = {"history"}
    return {k: v for k, v in record.items() if k not in hidden}


def build_facade(service: ShiningWorldService) -> ToolFacade:
    return ToolFacade(service)


# 兼容：旧命名
WorldBibleType = WorldBible
TokenEstimate = estimate_tokens
ProviderConfigType = ProviderConfig
