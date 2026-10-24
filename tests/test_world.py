"""世界观池子 + 提案审批 + 角色卡测试。"""

from __future__ import annotations

import pytest

from shining_world.common.errors import ToolError
from shining_world.world.character_sheet import (
    build_character_sheet,
    merge_character_patch,
    validate_character_sheet,
)

MINIMAL_SHEET = {
    "name": "林澈",
    "identity": "正派小队队长",
    "core_belief": "不带任何人掉队",
    "traits": {"stable": ["冷静", "谨慎"], "temporary": []},
    "hard_rule": ["禁止背后偷袭"],
}


def test_build_character_sheet_fills_defaults():
    sheet = build_character_sheet(MINIMAL_SHEET)
    assert sheet["char_id"].startswith("char_")
    assert sheet["traits"]["stable"] == ["冷静", "谨慎"]
    assert sheet["evolution_log"][0]["source"] == "manual"


def test_validate_character_sheet_reports_missing_fields():
    problems = validate_character_sheet({"name": "无名"})
    assert any("identity" in p for p in problems)
    assert any("hard_rule" in p for p in problems)
    assert any("traits" in p for p in problems)


def test_character_card_versioning_and_rollback(service):
    first = service.world.character.approve_card(build_character_sheet(MINIMAL_SHEET))
    changed = dict(MINIMAL_SHEET, core_belief="先保人再保任务")
    second = service.world.character.approve_card(build_character_sheet(changed, source="manual"))

    assert first["char_id"] == second["char_id"]
    assert second["version"] == 2

    back = service.world.character.rollback("林澈", 1)
    assert back["core_belief"] == "不带任何人掉队"


def test_secret_is_redacted_for_other_faction(service):
    sheet = build_character_sheet(
        dict(MINIMAL_SHEET, secret="其实是叛徒", secret_visible_to=["暗流"])
    )
    service.world.character.approve_card(sheet)

    hidden = service.world.character.get_card("林澈", viewer_faction="正派小队")
    assert hidden["secret_redacted"] is True
    assert "受控保密" in hidden["secret"]

    visible = service.world.character.get_card("林澈", viewer_faction="暗流")
    assert visible["secret_redacted"] is False
    assert visible["secret"] == "其实是叛徒"


def test_merge_patch_never_drops_stable_traits():
    base = build_character_sheet(MINIMAL_SHEET)
    merged = merge_character_patch(base, {"traits": {"stable": ["冷静", "多疑"]}})
    assert merged["traits"]["stable"] == ["冷静", "谨慎", "多疑"]


def test_proposal_approval_applies_change(service):
    proposal = service.world.proposals.submit(
        target="map",
        action="upsert",
        payload={"name": "雾港", "description": "常年有雾的港口城市", "rules": ["夜间封城"]},
    )
    assert service.world.map.count() == 0

    result = service.world.approve_proposal(proposal["proposal_id"])
    assert result["proposal"]["status"] == "approved"
    place = service.world.map.get("loc:雾港")
    assert place["rules"] == ["夜间封城"]


def test_proposal_rejection_does_not_touch_pool(service):
    proposal = service.world.proposals.submit(
        target="culture",
        action="upsert",
        payload={"name": "暗流", "description": "幕后势力"},
    )
    result = service.world.approve_proposal(proposal["proposal_id"], approved=False)
    assert result["status"] == "rejected"
    assert service.world.culture.count() == 0


def test_approving_twice_conflicts(service):
    proposal = service.world.proposals.submit(
        target="map",
        action="upsert",
        payload={"name": "内城"},
    )
    service.world.approve_proposal(proposal["proposal_id"])
    with pytest.raises(ToolError):
        service.world.approve_proposal(proposal["proposal_id"])


def test_invalid_proposal_payload_marks_failed(service):
    proposal = service.world.proposals.submit(
        target="character",
        action="create",
        payload={"name": "缺字段角色"},
    )
    with pytest.raises(ToolError):
        service.world.approve_proposal(proposal["proposal_id"])
    assert service.world.proposals.get(proposal["proposal_id"])["status"] == "failed"


def test_events_filtered_by_faction_and_stream(service):
    service.world.plot.add_event(
        "密信抵达",
        "密探网收到内城布防图",
        visible_factions=["暗流"],
        active_streams=["s_a"],
    )
    assert [e["title"] for e in service.world.plot.list_events(faction="暗流")] == ["密信抵达"]
    assert service.world.plot.list_events(faction="正派小队") == []
    assert service.world.plot.list_events(faction="暗流", stream_id="s_b") == []


def test_purge_expired_events(service):
    event = service.world.plot.add_event("短路事件", "只活一轮", ttl_rounds=1)
    service.world.plot.upsert(event["id"], dict(event, rounds_elapsed=1))
    removed = service.world.plot.purge_expired()
    assert removed == [event["id"]]
    assert service.world.plot.list_events() == []
