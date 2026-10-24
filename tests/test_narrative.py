"""推演引擎与蒸馏器测试（全部走本地 mock，不联网）。"""

from __future__ import annotations

import pytest

from shining_world.common.errors import ToolError
from shining_world.narrative.distiller import CharacterDistiller, _normalize_patch
from shining_world.world.character_sheet import build_character_sheet

SHEET = {
    "name": "林澈",
    "identity": "正派小队队长",
    "core_belief": "不带任何人掉队",
    "traits": {"stable": ["冷静"], "temporary": []},
    "hard_rule": ["禁止背后偷袭"],
    "tags": ["char:林澈"],
}


def _seed(service):
    service.world.plot.set_mainline_outline("雾港第七日封锁，证物必须出城。")
    service.world.map.upsert_place("雾港", description="常年有雾", rules=["夜间封城"])
    service.world.culture.upsert_faction("正派小队", description="护送证物的四人小队")
    service.world.character.approve_card(build_character_sheet(SHEET))


def test_step_appends_content_and_resets_cooldown(service):
    _seed(service)
    record = service.streams.create("正派小队视角", faction="正派小队", tags=["char:林澈"])

    result = service.engine.step(record.stream_id)
    assert result.text
    assert result.check["passed"] is True
    assert result.dry_run is False

    after = service.streams.get(record.stream_id)
    assert after.step_count == 1
    assert after.total_chars == len(result.text)
    assert after.status == "cooldown"


def test_dry_run_does_not_write(service):
    _seed(service)
    record = service.streams.create("试跑支线", faction="正派小队", tags=["char:林澈"])

    result = service.engine.step(record.stream_id, dry_run=True)
    assert result.text
    assert service.streams.full_text(record.stream_id) == ""
    assert service.streams.get(record.stream_id).step_count == 0


def test_context_contains_mainline_and_characters(service):
    _seed(service)
    record = service.streams.create("上下文支线", faction="正派小队", tags=["char:林澈"])

    context = service.builder.build(record.stream_id, query="雾港 林澈")
    assert context.characters, "应召回角色卡"
    assert context.characters[0]["name"] == "林澈"
    assert context.retrieval_strategy in {"tag", "tag+vector", "vector"}


def test_prompt_block_renders_expected_labels(service):
    _seed(service)
    record = service.streams.create("渲染支线", faction="正派小队", tags=["char:林澈"])
    context = service.builder.build(record.stream_id, query="林澈")
    block = context.to_prompt_block(mainline="雾港第七日封锁")
    assert "主线约束：" in block
    assert "出场角色：" in block
    assert "林澈" in block


def test_consistency_failure_freezes_only_that_stream(service, monkeypatch):
    _seed(service)
    bad = service.streams.create("违规支线", faction="正派小队", tags=["char:林澈"])
    good = service.streams.create("正常支线", faction="正派小队")

    monkeypatch.setattr(
        service.manager,
        "complete",
        lambda *a, **k: _FixedCompletion("林澈决定背后偷袭，很快得手。"),
    )
    result = service.engine.step(bad.stream_id)
    assert result.paused is True
    assert service.streams.get(bad.stream_id).status == "error"
    assert service.streams.full_text(bad.stream_id) == ""
    assert service.streams.get(good.stream_id).status == "cooldown"


def test_step_all_due_processes_each_stream_once(service):
    _seed(service)
    service.streams.create("A", faction="正派小队", tags=["char:林澈"])
    service.streams.create("B", faction="正派小队", tags=["char:林澈"])

    results = service.engine.step_all_due()
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert {r["stream_name"] for r in results} == {"A", "B"}
    # 夹具冷却为 0 秒 → 仍到期，但每次只推进一轮（step_count 递增而非重复计入同一轮）
    assert all(service.streams.get(r["stream_id"]).step_count == 1 for r in results)


def test_cooling_stream_is_not_stepped(service):
    _seed(service)
    record = service.streams.create("冷却中支线", faction="正派小队", cooldown_s=600, tags=["char:林澈"])
    service.streams.set_status(record.stream_id, "cooldown")  # 进入 600s 冷却
    assert service.engine.step_all_due() == []
    assert service.streams.get(record.stream_id).step_count == 0


def test_snapshot_proposal_created_when_threshold_reached(service):
    _seed(service)
    record = service.streams.create("长线支线", faction="正派小队", tags=["char:林澈"])
    service.streams.append_content(record.stream_id, "字" * 260)  # 夹具阈值 200

    proposal = service.engine.propose_snapshot(record.stream_id)
    assert proposal["snapshot"]["snapshot_id"].startswith("snap_")
    assert proposal["proposal"]["status"] == "pending"


class _FixedCompletion:
    def __init__(self, text: str) -> None:
        self.text = text
        self.provider = "stub"
        self.model = "stub-model"
        self.latency_ms = 1
        self.attempts = 1


def test_distiller_parses_fenced_json(service, monkeypatch):
    payload = """```json
    {"name": "林澈", "identity": "队长", "traits": {"stable": ["冷静"]}, "hard_rule": ["禁止背后偷袭"], "tags": ["char:林澈"]}
    ```"""
    monkeypatch.setattr(
        service.manager,
        "complete",
        lambda *a, **k: _FixedCompletion(payload),
    )
    result = service.distiller.distill("林澈", "林澈：都跟上，别掉队。")
    assert result["patch"]["traits"]["stable"] == ["冷静"]
    assert result["patch"]["tags"] == ["char:林澈"]


def test_distiller_raises_on_garbage(service, monkeypatch):
    monkeypatch.setattr(
        service.manager,
        "complete",
        lambda *a, **k: _FixedCompletion("抱歉，我无法回答。"),
    )
    with pytest.raises(ToolError):
        service.distiller.distill("林澈", "任意对话")


def test_distiller_requires_input(service):
    with pytest.raises(ToolError):
        service.distiller.distill("", "对话")
    with pytest.raises(ToolError):
        service.distiller.distill("林澈", "   ")


def test_normalize_patch_coerces_loose_shapes():
    patched = _normalize_patch(
        {"traits": ["冷静"], "hard_rule": "禁止偷袭、禁止撒谎", "bond": ["密探甲"]}
    )
    assert patched["traits"] == {"stable": ["冷静"], "temporary": []}
    assert patched["hard_rule"] == ["禁止偷袭", "禁止撒谎"]
    assert patched["bond"][0]["target"] == "密探甲"


def test_distiller_missing_json_block_is_error():
    with pytest.raises(ToolError):
        CharacterDistiller._parse_json("没有 JSON 的文本")
