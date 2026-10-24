"""工具门面测试：信封格式、参数校验、权限与审批闭环。"""

from __future__ import annotations

import pytest

from shining_world.world.character_sheet import build_character_sheet

SHEET = {
    "name": "林澈",
    "identity": "正派小队队长",
    "core_belief": "不带任何人掉队",
    "traits": {"stable": ["冷静"], "temporary": []},
    "hard_rule": ["禁止背后偷袭"],
    "tags": ["char:林澈"],
}


def test_status_envelope_shape(facade):
    result = facade.get_service_status()
    assert result["ok"] is True
    assert "workspace" in result and "world" in result


def test_provider_tools(facade):
    listed = facade.list_providers()
    assert listed["ok"] is True
    assert listed["count"] >= 1

    switched = facade.switch_default_provider("mock-local")
    assert switched["ok"] is True

    quota = facade.set_provider_quota("mock-local", max_concurrency=4, rpm=30)
    assert quota["ok"] is True
    assert quota["provider"]["max_concurrency"] == 4

    tested = facade.test_provider_connection()
    assert tested["ok"] is True


def test_invalid_arguments_return_error_envelope(facade):
    result = facade.switch_default_provider("")
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_unknown_provider_returns_not_found(facade):
    result = facade.switch_default_provider("不存在")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


def test_quota_requires_at_least_one_param(facade):
    result = facade.set_provider_quota("mock-local")
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_stream_tools_roundtrip(facade):
    created = facade.create_narrative_stream("主线大纲", faction="公共", cell=5, cooldown_s=0)
    assert created["ok"] is True
    stream_id = created["stream"]["stream_id"]

    stepped = facade.trigger_stream_step(stream_id)
    assert stepped["ok"] is True
    assert stepped["result"]["text"]

    content = facade.get_stream_content(stream_id)
    assert content["ok"] is True
    assert content["content"]

    paused = facade.pause_stream(stream_id)
    assert paused["stream"]["status"] == "paused"

    resumed = facade.resume_stream(stream_id)
    assert resumed["ok"] is True

    listed = facade.list_all_streams()
    assert listed["count"] == 1

    all_paused = facade.pause_all_streams()
    assert all_paused["count"] == 1
    assert facade.resume_all_streams()["ok"] is True


def test_step_missing_stream_is_not_found(facade):
    result = facade.trigger_stream_step("不存在的支线")
    assert result["ok"] is False
    assert result["error"]["code"] == "NOT_FOUND"


def test_tag_tools_and_faction_filter(facade):
    added = facade.add_tags("char:林澈", ["char:林澈", "faction:正派小队"], text="雾港队长", faction="正派小队")
    assert added["ok"] is True

    searched = facade.search_by_tags(["char:林澈"])
    assert searched["count"] == 1

    vectors = facade.vector_search("雾港的队长")
    assert vectors["ok"] is True

    filtered = facade.filter_by_faction("暗流")
    assert filtered["visible"] == []
    assert filtered["hidden"][0]["ref"] == "char:林澈"

    removed = facade.remove_tags("char:林澈", ["faction:正派小队"])
    assert removed["ok"] is True


def test_bad_tag_returns_error(facade):
    result = facade.add_tags("char:林澈", ["林澈"])
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"


def test_character_tools_with_permissions(facade):
    approved = facade.approve_character_card(
        dict(SHEET, secret="其实是叛徒", secret_visible_to=["暗流"])
    )
    assert approved["ok"] is True

    hidden = facade.get_character("林澈", viewer_faction="正派小队")
    assert hidden["character"]["secret_redacted"] is True

    shown = facade.get_character("林澈", viewer_faction="暗流")
    assert shown["character"]["secret"] == "其实是叛徒"

    rolled = facade.rollback_character("林澈", 1)
    assert rolled["ok"] is False  # 只有 1 个版本，历史里没有 v1
    assert rolled["error"]["code"] == "NOT_FOUND"


def test_character_card_validation_error(facade):
    result = facade.approve_character_card({"name": "残缺角色"})
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENT"
    assert result["error"]["detail"]["problems"]


def test_event_approval_flow(facade):
    pending = facade.add_ad_hoc_event("密信抵达", "暗流收到布防图", visible_factions=["暗流"])
    assert pending["status"] == "pending_approval"

    proposals = facade.list_pending_proposals()
    assert proposals["count"] == 1
    proposal_id = proposals["proposals"][0]["proposal_id"]

    decided = facade.decide_proposal(proposal_id, approved=True, note="同意")
    assert decided["ok"] is True

    events = facade.list_events(faction="暗流")
    assert events["count"] == 1

    direct = facade.add_ad_hoc_event("走廊事件", "临时插入", require_approval=False)
    assert direct["status"] == "created"

    removed = facade.remove_event(direct["event"]["id"])
    assert removed["removed"] is True


def test_distill_submits_proposal(facade):
    result = facade.distill_chat_to_character_sheet("林澈", "林澈：都跟上。", auto_submit=True)
    assert result["ok"] is True
    assert result["proposal"]["status"] == "pending"
    assert result["patch"]["name"] == "林澈"


def test_snapshot_tools(facade):
    created = facade.create_narrative_stream("记忆支线", cooldown_s=0)
    stream_id = created["stream"]["stream_id"]
    facade.trigger_stream_step(stream_id)

    snap = facade.create_stream_snapshot(stream_id, summary="队长拿到证物。", key_facts=["证物在手"])
    assert snap["ok"] is True
    snapshot_id = snap["snapshot"]["snapshot_id"]

    listed = facade.list_snapshots(stream_id)
    assert listed["count"] == 1

    approved = facade.approve_snapshot(stream_id, snapshot_id)
    assert approved["ok"] is True
    assert approved["status"] == "approved"


def test_consistency_tools(facade):
    facade.approve_character_card(SHEET)

    ooc = facade.check_character_ooc("林澈", "林澈背后偷袭守卫。")
    assert ooc["passed"] is False

    timeline = facade.check_timeline_conflict("第三天，队伍出城。", current_day=5)
    assert timeline["passed"] is False

    world_rule = facade.check_world_rule_conflict("雾港夜里亮灯。", place="未登记地点")
    assert world_rule["passed"] is True

    created = facade.create_narrative_stream("冻结支线", cooldown_s=0)
    paused = facade.pause_stream_on_error(created["stream"]["stream_id"], "OOC 告警")
    assert paused["stream"]["status"] == "error"
    assert paused["stream"]["last_error"] == "OOC 告警"


def test_place_and_faction_tools(facade):
    place = facade.upsert_place("雾港", description="常年有雾", rules=["夜间封城"])
    assert place["ok"] is True

    faction = facade.upsert_faction("正派小队", description="护送证物", allies=["城防军"])
    assert faction["ok"] is True

    mainline = facade.set_mainline_outline("雾港第七日封锁。")
    assert mainline["ok"] is True


def test_purge_stale_events(facade):
    facade.add_ad_hoc_event("短命事件", "只活一轮", ttl_rounds=1, require_approval=False)
    result = facade.purge_stale_events()
    assert result["ok"] is True


def test_unexpected_exception_becomes_internal_envelope(facade, monkeypatch):
    def boom():
        raise RuntimeError("模拟底层崩溃")

    monkeypatch.setattr(facade.service.manager, "default_name", boom)
    result = facade.get_service_status()
    assert result["ok"] is False
    assert result["error"]["code"] == "INTERNAL"
    assert "模拟底层崩溃" in result["error"]["message"]
