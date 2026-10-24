"""一致性校验测试：OOC / 时序 / 世界观规则。"""

from __future__ import annotations

import pytest

from shining_world.world.character_sheet import build_character_sheet

SHEET = build_character_sheet(
    {
        "name": "林澈",
        "identity": "正派小队队长",
        "core_belief": "不带任何人掉队",
        "traits": {"stable": ["冷静"], "temporary": []},
        "speech_style": "简短克制；禁用词汇：混蛋、去死",
        "hard_rule": ["禁止背后偷袭"],
    }
)


def test_detects_hard_rule_violation(service):
    text = "林澈决定背后偷袭守卫。"
    result = service.checker.check_all(text, characters=[SHEET])
    assert result["passed"] is False
    assert result["violations"][0]["kind"] == "ooc"
    assert "背后偷袭" in result["violations"][0]["message"]


def test_detects_banned_word_as_warning(service):
    result = service.checker.check_all("林澈骂了一句混蛋。", characters=[SHEET])
    assert result["passed"] is True  # warning 不阻断
    assert result["warning_count"] == 1
    assert "混蛋" in result["violations"][0]["evidence"]


def test_detects_stable_trait_opposite(service):
    result = service.checker.check_all("林澈暴怒地掀翻了桌子。", characters=[SHEET])
    assert any("冷静" in v["message"] for v in result["violations"])


def test_clean_text_passes(service):
    result = service.checker.check_all("林澈压低声音，先让队员退回巷口。", characters=[SHEET])
    assert result["passed"] is True
    assert result["violations"] == []


def test_timeline_backwards_is_blocking(service):
    result = service.checker.check_all("第二天清晨，队伍抵达城门。", current_day=5)
    assert result["passed"] is False
    assert result["violations"][0]["kind"] == "timeline"


def test_timeline_forward_is_fine(service):
    result = service.checker.check_all("第六天夜里，队伍出城。", current_day=5)
    assert result["passed"] is True


def test_timeline_skipped_when_no_current_day(service):
    result = service.checker.check_all("第一天，队伍集结。", current_day=0)
    assert result["passed"] is True


def test_world_rule_conflict_needs_place(service):
    # 地点未入库时不报错，也不误报
    result = service.checker.check_all("雾港夜里亮着灯。", place="未登记地点")
    assert result["passed"] is True


def test_multiple_characters_are_all_checked(service):
    other = build_character_sheet(
        {
            "name": "密探甲",
            "identity": "密探",
            "core_belief": "完成任务优先",
            "traits": {"stable": ["忠诚"], "temporary": []},
            "hard_rule": ["禁止出卖雇主"],
        }
    )
    result = service.checker.check_all(
        "林澈背后偷袭得手，密探甲开始出卖雇主。",
        characters=[SHEET, other],
    )
    kinds = {v["kind"] for v in result["violations"]}
    assert kinds == {"ooc"}
    assert len(result["violations"]) >= 2


@pytest.mark.parametrize("text", ["", "   ", "无冲突的一段普通剧情。"])
def test_blank_and_clean_texts(service, text: str):
    result = service.checker.check_all(text, characters=[SHEET])
    assert result["passed"] is True
