"""剧情推演引擎：单步生成 → 一致性校验 → 落盘 → 可选快照提案。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from ..common.errors import ErrorCode, ToolError
from ..common.text import normalize_ws
from ..common.ids import now_iso
from ..consistency.checker import ConsistencyChecker
from ..providers.provider_manager import ProviderManager
from ..streams.manager import StreamManager
from ..streams.snapshot import SnapshotManager
from ..world.pools import WorldBible
from .context import ContextBuilder, NarrativeContext
from .distiller import CharacterDistiller
from .prompts import PromptLibrary


@dataclass
class StepResult:
    """一次步进的结果。"""

    stream_id: str
    stream_name: str
    text: str
    provider: str
    model: str
    latency_ms: int
    attempts: int
    check: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    paused: bool = False
    snapshot_proposal: dict[str, Any] | None = None
    dry_run: bool = False

    def to_public(self) -> dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "stream_name": self.stream_name,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "attempts": self.attempts,
            "check": self.check,
            "context": self.context,
            "paused": self.paused,
            "snapshot_proposal": self.snapshot_proposal,
            "dry_run": self.dry_run,
            "text": self.text,
        }


class NarrativeEngine:
    """把检索、拼装、模型调用、校验、记忆串成一条链。"""

    def __init__(
        self,
        world: WorldBible,
        streams: StreamManager,
        snapshots: SnapshotManager,
        retrieval_builder: ContextBuilder,
        manager: ProviderManager,
        checker: ConsistencyChecker,
        distiller: CharacterDistiller,
        prompts: PromptLibrary,
    ) -> None:
        self.world = world
        self.streams = streams
        self.snapshots = snapshots
        self.builder = retrieval_builder
        self.manager = manager
        self.checker = checker
        self.distiller = distiller
        self.prompts = prompts
        self._lock = threading.RLock()

    # ---------- 单步推演 ----------
    def step(
        self,
        stream_id: str,
        *,
        extra_tags: list[str] | None = None,
        hint: str = "",
        dry_run: bool = False,
        max_tokens: int = 700,
    ) -> StepResult:
        record = self.streams.get(stream_id)

        context = self.builder.build(stream_id, extra_tags=extra_tags, query=hint)
        mainline = ""
        mainline_record = self.world.plot.mainline()
        if mainline_record:
            mainline = str(mainline_record.get("outline", ""))[:600]

        block = context.to_prompt_block(mainline=mainline)
        if hint:
            block += f"\n本轮提示：{hint}"

        completion = self.manager.complete(
            [
                {"role": "system", "content": self.prompts.story_system},
                {"role": "user", "content": self.prompts.story_user(block)},
            ],
            temperature=0.9,
            max_tokens=max_tokens,
        )
        text = _clean_text(completion.text, self.streams.settings if hasattr(self.streams, "settings") else None)

        check = self.checker.check_all(
            text,
            characters=context.characters,
            current_day=self._current_day(stream_id),
            place=context.places[0].get("name", "") if context.places else "",
        )

        result = StepResult(
            stream_id=record.stream_id,
            stream_name=record.name,
            text=text,
            provider=completion.provider,
            model=completion.model,
            latency_ms=completion.latency_ms,
            attempts=completion.attempts,
            check=check,
            context=context.to_public(),
            dry_run=dry_run,
        )

        if dry_run:
            return result

        if not check["passed"]:
            # 冲突：不写入正文，只冻结该支线并记录告警
            self.streams.set_status(
                record.stream_id,
                "error",
                error="一致性校验未通过：" + "；".join(v["message"] for v in check["violations"] if v["severity"] == "blocking"),
            )
            result.paused = True
            return result

        self.streams.append_content(
            record.stream_id,
            text,
            meta={
                "provider": completion.provider,
                "model": completion.model,
                "strategy": context.retrieval_strategy,
                "warnings": [v["message"] for v in check["violations"]],
            },
        )
        self._advance_events(record.stream_id, context)

        if self.snapshots.should_snapshot(record.stream_id):
            result.snapshot_proposal = self.propose_snapshot(record.stream_id)
        return result

    # ---------- 快照 ----------
    def propose_snapshot(self, stream_id: str) -> dict[str, Any]:
        """用模型把当前支线剧情压缩成快照提案，等待人工审批。"""
        record = self.streams.get(stream_id)
        full = self.streams.full_text(stream_id)
        excerpt = full[-6000:]
        try:
            completion = self.manager.complete(
                [
                    {"role": "system", "content": self.prompts.snapshot_system},
                    {"role": "user", "content": self.prompts.snapshot_user(record.name, excerpt)},
                ],
                temperature=0.2,
                max_tokens=600,
            )
            payload = CharacterDistiller._parse_json(completion.text)
            summary = str(payload.get("summary", "") or "").strip()
            key_facts = [str(x).strip() for x in payload.get("key_facts") or [] if str(x).strip()]
            changes = [str(x).strip() for x in payload.get("character_changes") or [] if str(x).strip()]
        except (ToolError, Exception) as exc:  # noqa: BLE001 - 模型不可用时退化为抽取式摘要
            summary = _extractive_summary(excerpt, 180)
            key_facts = _split_sentences(excerpt)[-4:]
            changes = []
            source = "rule-fallback"
            proposal = self.snapshots.create_proposal(
                stream_id,
                summary=summary,
                key_facts=key_facts,
                character_changes=changes,
                source=source,
            )
            proposal["fallback_reason"] = str(exc)
            return proposal

        return self.snapshots.create_proposal(
            stream_id,
            summary=summary,
            key_facts=key_facts,
            character_changes=changes,
            source="model",
        )

    # ---------- 自动推进 ----------
    def step_all_due(self, *, limit: int = 9) -> list[dict[str, Any]]:
        """把所有冷却结束的支线各推进一步（DSH 轮询调用）。"""
        results: list[dict[str, Any]] = []
        for record in self.streams.due_streams()[:limit]:
            try:
                result = self.step(record.stream_id)
            except ToolError as exc:
                self.streams.set_status(record.stream_id, "error", error=exc.message)
                results.append(
                    {
                        "stream_id": record.stream_id,
                        "ok": False,
                        "error": {"code": str(exc.code), "message": exc.message},
                    }
                )
                continue
            results.append({"ok": True, **result.to_public()})
        return results

    # ---------- 内部 ----------
    def _advance_events(self, stream_id: str, context: NarrativeContext) -> None:
        """本轮生效的临时事件计数 +1，供 TTL 清理。"""
        if not context.events:
            return
        with self._lock:
            for event in context.events:
                event_id = event.get("id")
                if not event_id:
                    continue
                current = dict(event)
                current["rounds_elapsed"] = int(current.get("rounds_elapsed") or 0) + 1
                self.world.plot.upsert(event_id, current)

    def _current_day(self, stream_id: str) -> int:
        """从快照推理当前时间线进度（无则 0 表示不校验）。"""
        for snap in self.snapshots.latest_snapshots(stream_id, limit=1):
            data = self.snapshots.load_snapshot(stream_id, snap["snapshot_id"])
            day = int(data.get("day") or 0)
            if day:
                return day
        return 0


# ---------- 工具函数 ----------
_MD_PREFIXES = ("#", "**", "- ", "* ", ">", "```")


def _clean_text(text: str, _settings: Any = None) -> str:
    """去掉模型偶发的 Markdown 标记与首尾引号。"""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            continue
        for prefix in _MD_PREFIXES:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix) :].strip()
        lines.append(stripped)
    cleaned = normalize_ws("".join(lines))
    return cleaned.strip("“”\"' ")


def _split_sentences(text: str) -> list[str]:
    import re

    return [s.strip() for s in re.split(r"(?<=[。！？!?])", text) if s.strip()]


def _extractive_summary(text: str, max_chars: int) -> str:
    """抽取式摘要兜底：取末段具有推进感的句子。"""
    sentences = _split_sentences(text)
    picked: list[str] = []
    total = 0
    for sentence in reversed(sentences):
        if total + len(sentence) > max_chars:
            break
        picked.append(sentence)
        total += len(sentence)
    return "".join(reversed(picked)) or text[-max_chars:]
