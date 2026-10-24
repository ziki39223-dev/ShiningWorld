"""MCP Server：工具注册与生命周期。

工具函数只做「参数透传 → Facade → 信封」，业务逻辑全在 ToolFacade 里。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer

from ..config.settings import AppSettings
from ..tools.bootstrap import ShiningWorldService, build_service_from_settings, persist_indexes
from ..tools.facade import ToolFacade, build_facade

_log = logging.getLogger("shining_world.server")

SERVER_NAME = "shining-world"
SERVER_VERSION = "1.0.0"
SERVER_INSTRUCTIONS = (
    "闪亮大世界 ShiningWorld —— 多支线群像剧情推演调度服务。\n"
    "顶层链路：DSH 九宫格主控台 →(MCP stdio/SSE)→ 本服务 →(OpenAI 兼容 API)→ 模型。\n"
    "典型流程：\n"
    "1) list_providers / test_provider_connection 确认模型源可用；\n"
    "2) set_mainline_outline / upsert_place / upsert_faction / approve_character_card 录入世界观；\n"
    "3) create_narrative_stream 建 9 条支线（cell=1..9，第 5 格为主线）；\n"
    "4) step_all_due_streams 或 trigger_stream_step 推进剧情，get_stream_content 拉增量文本；\n"
    "5) 长线运行后 create_stream_snapshot → approve_snapshot 收拢记忆；\n"
    "6) 任何世界观改动走 list_pending_proposals → decide_proposal 人工审批。\n"
    "一致性校验失败时仅冻结对应支线（pause_stream_on_error），不影响其他支线。"
)


def register_tools(server: MCPServer, facade: ToolFacade) -> None:
    """把全部工具注册到 MCP Server。"""

    # ---------- 系统 ----------
    @server.tool(
        name="get_service_status",
        description="查看服务整体状态：工作区路径、支线数、世界观统计、默认服务商、待审提案数",
    )
    def get_service_status() -> dict[str, Any]:
        return facade.get_service_status()

    # ---------- 5.1 模型服务商管理 ----------
    @server.tool(
        name="list_providers",
        description="列出全部 API 服务商（付费 + 免费池），含优先级、并发、限速、可用性与最近错误",
    )
    def list_providers() -> dict[str, Any]:
        return facade.list_providers()

    @server.tool(
        name="switch_default_provider",
        description="切换全局默认模型源（其余服务商仍作为故障降级备选）",
    )
    def switch_default_provider(name: str) -> dict[str, Any]:
        """切换默认服务商。

        Args:
            name: 服务商名称，取自 list_providers 的 providers[].name。
        """
        return facade.switch_default_provider(name)

    @server.tool(
        name="set_provider_quota",
        description="设置单服务商的并发上限与每分钟请求上限（限流保护）",
    )
    def set_provider_quota(
        name: str,
        max_concurrency: int | None = None,
        rpm: int | None = None,
    ) -> dict[str, Any]:
        """调整服务商配额。

        Args:
            name: 服务商名称。
            max_concurrency: 最大并发请求数（可选）。
            rpm: 每分钟请求上限（可选）。
        """
        return facade.set_provider_quota(name, max_concurrency, rpm)

    @server.tool(
        name="test_provider_connection",
        description="连通性测试；不传 name 时逐个测试全部服务商",
    )
    def test_provider_connection(name: str | None = None) -> dict[str, Any]:
        """测试服务商连通性。

        Args:
            name: 服务商名称；为空测试全部。
        """
        return facade.test_provider_connection(name)

    # ---------- 5.2 叙事流管理器 ----------
    @server.tool(
        name="create_narrative_stream",
        description="创建叙事支线（视角、阵营、冷却时长、标签、九宫格位置 cell=1..9，5 为主线）",
    )
    def create_narrative_stream(
        name: str,
        faction: str = "",
        perspective: str = "",
        cooldown_s: int | None = None,
        tags: list[str] | None = None,
        cell: int = 0,
    ) -> dict[str, Any]:
        """创建支线。

        Args:
            name: 支线名称，如「正派小队视角」。
            faction: 所属阵营（用于信息隔离）。
            perspective: 叙事视角说明。
            cooldown_s: 冷却秒数；为空用配置默认值。
            tags: 该支线常驻检索标签，如 ["char:林澈", "loc:雾港"]。
            cell: 九宫格编号 1-9，5 为主线。
        """
        return facade.create_narrative_stream(name, faction, perspective, cooldown_s, tags, cell)

    @server.tool(
        name="trigger_stream_step",
        description="手动步进指定支线：检索素材 → 调模型 → 一致性校验 → 写入 content.log",
    )
    def trigger_stream_step(
        stream_id: str,
        hint: str = "",
        dry_run: bool = False,
        max_tokens: int = 700,
    ) -> dict[str, Any]:
        """步进一条支线。

        Args:
            stream_id: 支线 ID 或名称。
            hint: 本轮临时提示（可选）。
            dry_run: 只生成不落盘，用于预览。
            max_tokens: 单轮生成长度上限。
        """
        return facade.trigger_stream_step(stream_id, hint, dry_run, max_tokens)

    @server.tool(
        name="step_all_due_streams",
        description="把所有冷却结束的支线各推进一步（九宫格轮询刷新用），返回每格结果",
    )
    def step_all_due_streams(limit: int = 9) -> dict[str, Any]:
        """批量推进到期支线。

        Args:
            limit: 单次最多推进几条（默认 9，对应九宫格）。
        """
        return facade.step_all_due_streams(limit)

    @server.tool(
        name="get_stream_content",
        description="读取支线增量文本（DSH 卡片实时展示），支持 since_chars 增量拉取",
    )
    def get_stream_content(
        stream_id: str,
        since_chars: int = 0,
        limit_chars: int = 4000,
    ) -> dict[str, Any]:
        """读取支线内容。

        Args:
            stream_id: 支线 ID 或名称。
            since_chars: 已读到的字符偏移。
            limit_chars: 本次最多返回多少字符。
        """
        return facade.get_stream_content(stream_id, since_chars, limit_chars)

    @server.tool(
        name="list_all_streams",
        description="查看全部支线状态（运行/暂停/冷却/告警）与累计字数",
    )
    def list_all_streams() -> dict[str, Any]:
        return facade.list_all_streams()

    @server.tool(name="pause_stream", description="暂停单支线（冻结该支线计时器，不影响其他支线）")
    def pause_stream(stream_id: str) -> dict[str, Any]:
        return facade.pause_stream(stream_id)

    @server.tool(name="resume_stream", description="恢复单支线（重新进入冷却倒计时）")
    def resume_stream(stream_id: str) -> dict[str, Any]:
        return facade.resume_stream(stream_id)

    @server.tool(name="pause_all_streams", description="全局冻结：暂停所有支线")
    def pause_all_streams() -> dict[str, Any]:
        return facade.pause_all_streams()

    @server.tool(name="resume_all_streams", description="全局继续：恢复所有支线")
    def resume_all_streams() -> dict[str, Any]:
        return facade.resume_all_streams()

    # ---------- 5.3 检索引擎 ----------
    @server.tool(
        name="add_tags",
        description="给实体批量打标签（char:/loc:/faction:/event:/plot:/rule:），提供 text 时同步写入向量库",
    )
    def add_tags(ref: str, tags: list[str], text: str = "", faction: str = "") -> dict[str, Any]:
        """打标签并建索引。

        Args:
            ref: 实体引用，如 char:林澈 / loc:雾港。
            tags: 标签数组，必须带规范前缀。
            text: 实体正文（用于向量兜底召回）。
            faction: 所属阵营（用于权限过滤）。
        """
        return facade.add_tags(ref, tags, text, faction)

    @server.tool(name="remove_tags", description="删除实体的指定标签")
    def remove_tags(ref: str, tags: list[str]) -> dict[str, Any]:
        return facade.remove_tags(ref, tags)

    @server.tool(
        name="search_by_tags",
        description="纯标签精确检索（优先执行，不走向量），match_all=false 为并集",
    )
    def search_by_tags(
        tags: list[str],
        match_all: bool = True,
        faction: str = "",
        limit: int = 20,
    ) -> dict[str, Any]:
        """标签检索。

        Args:
            tags: 标签数组。
            match_all: True=交集（全部命中），False=并集。
            faction: 只看该阵营可见内容。
            limit: 返回条数上限。
        """
        return facade.search_by_tags(tags, match_all, faction, limit)

    @server.tool(
        name="vector_search",
        description="语义向量召回（仅当标签命中不足时兜底使用）",
    )
    def vector_search(query: str, top_k: int = 6, faction: str = "") -> dict[str, Any]:
        """向量检索。

        Args:
            query: 自然语言查询（通常是最近剧情或本轮提示）。
            top_k: 返回条数。
            faction: 只看该阵营可见内容。
        """
        return facade.vector_search(query, top_k, faction)

    @server.tool(
        name="filter_by_faction",
        description="按阵营权限过滤内容，实现多阵营信息隔离",
    )
    def filter_by_faction(faction: str, refs: list[str] | None = None) -> dict[str, Any]:
        """阵营过滤。

        Args:
            faction: 当前视角阵营。
            refs: 待过滤的实体引用；为空则过滤全部索引条目。
        """
        return facade.filter_by_faction(faction, refs)

    # ---------- 5.4 世界观池子 ----------
    @server.tool(
        name="set_mainline_outline",
        description="录入主线大纲与时序约束（生成上下文的第一优先级约束）",
    )
    def set_mainline_outline(
        outline: str,
        timeline: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """录入主线。

        Args:
            outline: 主线大纲文本。
            timeline: 时序节点数组，如 [{"day": 3, "event": "雾港封锁"}]。
        """
        return facade.set_mainline_outline(outline, timeline)

    @server.tool(
        name="add_ad_hoc_event",
        description="插入临时定向事件；默认生成提案需人工审批，require_approval=false 直接入库（初始化用）",
    )
    def add_ad_hoc_event(
        title: str,
        content: str,
        visible_factions: list[str] | None = None,
        active_streams: list[str] | None = None,
        tags: list[str] | None = None,
        ttl_rounds: int = 0,
        require_approval: bool = True,
    ) -> dict[str, Any]:
        """插入临时事件。

        Args:
            title: 事件标题。
            content: 事件内容。
            visible_factions: 可见阵营列表（空=所有阵营可见）。
            active_streams: 生效支线 ID 列表（空=所有支线）。
            tags: 事件标签。
            ttl_rounds: 存活轮数，0=长期有效。
            require_approval: 是否走人工审批。
        """
        return facade.add_ad_hoc_event(
            title, content, visible_factions, active_streams, tags, ttl_rounds, require_approval
        )

    @server.tool(name="list_events", description="查询临时事件（可按阵营 / 支线过滤）")
    def list_events(faction: str = "", stream_id: str = "") -> dict[str, Any]:
        return facade.list_events(faction, stream_id)

    @server.tool(name="remove_event", description="删除指定的临时事件")
    def remove_event(event_id: str) -> dict[str, Any]:
        return facade.remove_event(event_id)

    @server.tool(
        name="distill_chat_to_character_sheet",
        description="对话日志自动蒸馏生成角色卡初稿；默认提交审批，不直接入库",
    )
    def distill_chat_to_character_sheet(
        character_name: str,
        dialogue: str,
        base_character: str = "",
        auto_submit: bool = True,
    ) -> dict[str, Any]:
        """蒸馏角色卡。

        Args:
            character_name: 角色名。
            dialogue: 对话 / 剧情片段。
            base_character: 已有角色名（给定时按补丁合并）。
            auto_submit: 是否自动提交审批队列。
        """
        return facade.distill_chat_to_character_sheet(
            character_name, dialogue, base_character, auto_submit
        )

    @server.tool(
        name="approve_character_card",
        description="人工审核并归档角色卡（生成新版本，保留历史可回滚）",
    )
    def approve_character_card(
        sheet: dict[str, Any],
        note: str = "",
        approved_by: str = "human",
    ) -> dict[str, Any]:
        """归档角色卡。

        Args:
            sheet: 角色卡 JSON（char_id 可省略，name/identity/core_belief/hard_rule/traits.stable 必填）。
            note: 审核备注。
            approved_by: 审核人标识。
        """
        return facade.approve_character_card(sheet, note, approved_by)

    @server.tool(
        name="get_character",
        description="按查看阵营权限读取角色资料（secret 字段受控）",
    )
    def get_character(name_or_id: str, viewer_faction: str = "") -> dict[str, Any]:
        """读取角色卡。

        Args:
            name_or_id: 角色名或 char_id。
            viewer_faction: 查看方阵营（决定能否看到 secret）。
        """
        return facade.get_character(name_or_id, viewer_faction)

    @server.tool(name="rollback_character", description="角色卡版本回滚到指定历史版本")
    def rollback_character(name_or_id: str, version: int) -> dict[str, Any]:
        return facade.rollback_character(name_or_id, version)

    @server.tool(
        name="upsert_place",
        description="录入 / 更新地图池地点（地点名、描述、归属阵营、地点规则、标签）",
    )
    def upsert_place(
        name: str,
        description: str = "",
        faction: str = "",
        rules: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return facade.upsert_place(name, description, faction, rules, tags)

    @server.tool(
        name="upsert_faction",
        description="录入 / 更新人文池势力（描述、立场、盟友、敌对、标签）",
    )
    def upsert_faction(
        name: str,
        description: str = "",
        stance: str = "neutral",
        allies: list[str] | None = None,
        enemies: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return facade.upsert_faction(name, description, stance, allies, enemies, tags)

    @server.tool(
        name="list_places",
        description="列出地图池地点，可按归属阵营过滤（空归属视为公共地点）",
    )
    def list_places(faction: str = "") -> dict[str, Any]:
        """列出地点。

        Args:
            faction: 只看该阵营可见地点（公共地点始终可见）。
        """
        return facade.list_places(faction)

    @server.tool(name="get_place", description="按名称读取单个地点档案（描述、归属阵营、地点规则、标签）")
    def get_place(name: str) -> dict[str, Any]:
        return facade.get_place(name)

    @server.tool(name="remove_place", description="删除地点，并同步从标签索引与向量库撤下")
    def remove_place(name: str) -> dict[str, Any]:
        return facade.remove_place(name)

    @server.tool(name="list_factions", description="列出人文池全部势力（立场、盟友、敌对、标签）")
    def list_factions() -> dict[str, Any]:
        return facade.list_factions()

    @server.tool(name="get_faction", description="按名称读取单个势力档案")
    def get_faction(name: str) -> dict[str, Any]:
        return facade.get_faction(name)

    @server.tool(name="remove_faction", description="删除势力，并同步从标签索引与向量库撤下")
    def remove_faction(name: str) -> dict[str, Any]:
        return facade.remove_faction(name)

    # ---------- 提案审批 ----------
    @server.tool(
        name="list_pending_proposals",
        description="查看提案队列（世界观变更 / 角色蒸馏 / 快照），status 取 pending/approved/rejected/failed",
    )
    def list_pending_proposals(status: str = "pending") -> dict[str, Any]:
        return facade.list_pending_proposals(status)

    @server.tool(
        name="decide_proposal",
        description="审批提案：approved=true 落库并保留修改日志，false 仅记录驳回",
    )
    def decide_proposal(proposal_id: str, approved: bool = True, note: str = "") -> dict[str, Any]:
        return facade.decide_proposal(proposal_id, approved, note)

    # ---------- 5.5 快照记忆 ----------
    @server.tool(
        name="create_stream_snapshot",
        description="生成记忆快照提案；不传 summary 时自动用模型压缩当前支线剧情",
    )
    def create_stream_snapshot(
        stream_id: str,
        summary: str = "",
        key_facts: list[str] | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        """生成快照。

        Args:
            stream_id: 支线 ID 或名称。
            summary: 人工撰写的摘要；为空则自动压缩。
            key_facts: 关键事实列表（人工填写时用）。
            source: 来源标记。
        """
        return facade.create_stream_snapshot(stream_id, summary, key_facts, source)

    @server.tool(
        name="approve_snapshot",
        description="人工审核快照：归档并返回上下文裁剪范围（保留最近 N 字符）",
    )
    def approve_snapshot(stream_id: str, snapshot_id: str, note: str = "") -> dict[str, Any]:
        return facade.approve_snapshot(stream_id, snapshot_id, note)

    @server.tool(name="list_snapshots", description="列出某条支线的全部快照及其状态")
    def list_snapshots(stream_id: str) -> dict[str, Any]:
        return facade.list_snapshots(stream_id)

    @server.tool(name="purge_stale_events", description="清理过期临时事件，控制上下文长度")
    def purge_stale_events() -> dict[str, Any]:
        return facade.purge_stale_events()

    # ---------- 5.6 一致性校验 ----------
    @server.tool(
        name="check_character_ooc",
        description="校验角色行为是否突破 hard_rule 底线（禁止词 / 稳定性格矛盾）",
    )
    def check_character_ooc(character: str, text: str, viewer_faction: str = "") -> dict[str, Any]:
        return facade.check_character_ooc(character, text, viewer_faction)

    @server.tool(
        name="check_timeline_conflict",
        description="检测时序矛盾：正文出现的天数不得早于当前进度",
    )
    def check_timeline_conflict(text: str, current_day: int = 0) -> dict[str, Any]:
        return facade.check_timeline_conflict(text, current_day)

    @server.tool(
        name="check_world_rule_conflict",
        description="跨世界观池子设定冲突检测（地点规则 / 阵营设定）",
    )
    def check_world_rule_conflict(text: str, place: str = "") -> dict[str, Any]:
        return facade.check_world_rule_conflict(text, place)

    @server.tool(
        name="pause_stream_on_error",
        description="校验失败时冻结指定支线并告警，其他支线继续运行",
    )
    def pause_stream_on_error(stream_id: str, reason: str = "") -> dict[str, Any]:
        return facade.pause_stream_on_error(stream_id, reason)


@asynccontextmanager
async def server_lifespan(_server: MCPServer) -> AsyncIterator[None]:
    """进程生命周期：启动/退出日志，退出前把索引刷盘。"""
    _log.info("MCP Server 启动：%s v%s", SERVER_NAME, SERVER_VERSION)
    try:
        yield
    finally:
        service: ShiningWorldService | None = getattr(_server, "_sw_service", None)
        if service is not None:
            try:
                persist_indexes(service)
                _log.info("索引已刷盘")
            except Exception as exc:  # noqa: BLE001 - 退出路径不允许再抛
                _log.warning("索引刷盘失败：%s", exc)
        _log.info("MCP Server 退出：%s", SERVER_NAME)


def build_server(settings: AppSettings) -> MCPServer:
    """按配置构建可运行的 MCP Server（尚未启动传输）。"""
    service = build_service_from_settings(settings)
    facade = build_facade(service)
    server = MCPServer(
        name=SERVER_NAME,
        version=SERVER_VERSION,
        instructions=SERVER_INSTRUCTIONS,
        lifespan=server_lifespan,
        log_level=settings.server.log_level,  # type: ignore[arg-type]
    )
    register_tools(server, facade)
    server._sw_service = service  # type: ignore[attr-defined]
    _log.info(
        "装配完成：workspace=%s streams=%s providers=%s",
        settings.workspace_root,
        len(service.streams.list()),
        len(settings.providers),
    )
    return server
