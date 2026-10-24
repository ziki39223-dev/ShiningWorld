"""回归测试：同名角色卡以 create 动作提案时不得覆盖已有 hard_rule。"""

from __future__ import annotations

from shining_world.world.character_sheet import build_character_sheet

BASE = {
    "name": "林澈",
    "identity": "正派小队队长",
    "core_belief": "不带任何人掉队",
    "traits": {"stable": ["冷静"], "temporary": []},
    "hard_rule": ["禁止背后偷袭", "禁止抛弃队友"],
}


def test_same_name_create_proposal_merges_hard_rule(service):
    service.world.character.approve_card(build_character_sheet(BASE))
    proposal = service.world.proposals.submit(
        target="character",
        action="create",
        payload={"name": "林澈", "hard_rule": ["林澈不得背弃同行者"]},
    )
    service.world.approve_proposal(proposal["proposal_id"])

    card = service.world.character.get_card("林澈")
    assert "禁止背后偷袭" in card["hard_rule"]
    assert "禁止抛弃队友" in card["hard_rule"]
    assert "林澈不得背弃同行者" in card["hard_rule"]
    assert card["version"] == 2


def test_patch_proposal_never_drops_stable_traits(service):
    service.world.character.approve_card(build_character_sheet(BASE))
    proposal = service.world.proposals.submit(
        target="character",
        action="patch",
        payload={"name": "林澈", "traits": {"stable": ["多疑"]}},
    )
    service.world.approve_proposal(proposal["proposal_id"])

    card = service.world.character.get_card("林澈")
    assert card["traits"]["stable"] == ["冷静", "多疑"]


def test_new_character_create_still_creates(service):
    proposal = service.world.proposals.submit(
        target="character",
        action="create",
        payload={
            "name": "新人",
            "identity": "旅人",
            "core_belief": "走到尽头",
            "traits": {"stable": ["沉默"], "temporary": []},
            "hard_rule": ["禁止说谎"],
        },
    )
    result = service.world.approve_proposal(proposal["proposal_id"])
    assert result["applied"]["name"] == "新人"
    assert result["applied"]["version"] == 1
