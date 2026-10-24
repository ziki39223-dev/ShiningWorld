"""地图池 / 人文池 CRUD 测试（含索引同步撤下）。"""

from __future__ import annotations

import pytest

from shining_world.common.errors import ToolError


def test_upsert_and_list_places(service):
    service.world.map.upsert_place("雾港", description="常年有雾", rules=["夜间封城"])
    service.world.map.upsert_place("潮汐钟楼", description="内城最高处", faction="城防军")

    rows = service.world.map.list_places()
    assert [r["name"] for r in rows] == ["潮汐钟楼", "雾港"]


def test_list_places_filters_by_faction(service):
    service.world.map.upsert_place("公共广场")
    service.world.map.upsert_place("密道", faction="暗流")

    visible = service.world.map.list_places(faction="正派小队")
    names = {r["name"] for r in visible}
    assert "公共广场" in names
    assert "密道" not in names


def test_get_place_by_name(service):
    service.world.map.upsert_place("雾港", description="港口")
    assert service.world.map.get_place("雾港")["description"] == "港口"

    with pytest.raises(ToolError) as exc:
        service.world.map.get_place("不存在")
    assert exc.value.code == "NOT_FOUND"


def test_remove_place_clears_indexes(service):
    service.world.map.upsert_place("雾港", description="港口")
    assert service.retrieval.tags.tags_of("loc:雾港")
    assert service.retrieval.vectors.search("雾港", top_k=5)

    result = service.world.map.remove_place("雾港")
    assert result["removed"] is True

    assert service.world.map.list_places() == []
    assert service.retrieval.tags.tags_of("loc:雾港") == []
    assert service.retrieval.vectors.search("雾港", top_k=5) == []


def test_remove_missing_place_is_not_found(service):
    with pytest.raises(ToolError) as exc:
        service.world.map.remove_place("不存在")
    assert exc.value.code == "NOT_FOUND"
    assert "available" in exc.value.detail


def test_upsert_and_list_factions(service):
    service.world.culture.upsert_faction("暗流", description="情报网", stance="neutral")
    service.world.culture.upsert_faction("正派小队", description="四人小队", allies=["城防军"])

    rows = service.world.culture.list_factions()
    assert [r["name"] for r in rows] == ["暗流", "正派小队"]


def test_get_faction_by_name(service):
    service.world.culture.upsert_faction("暗流", description="情报网")
    assert service.world.culture.get_faction("暗流")["description"] == "情报网"

    with pytest.raises(ToolError):
        service.world.culture.get_faction("不存在")


def test_remove_faction_clears_indexes(service):
    service.world.culture.upsert_faction("暗流", description="情报网")
    assert service.retrieval.tags.tags_of("faction:暗流")

    result = service.world.culture.remove_faction("暗流")
    assert result["removed"] is True

    assert service.world.culture.list_factions() == []
    assert service.retrieval.tags.tags_of("faction:暗流") == []


def test_remove_missing_faction_is_not_found(service):
    with pytest.raises(ToolError):
        service.world.culture.remove_faction("无此势力")


def test_remove_ref_drops_all_tags_of_entity(tmp_path):
    from shining_world.retrieval.tag_index import TagIndex

    index = TagIndex(tmp_path / "index.json")
    index.add_tags("char:林澈", ["char:林澈", "faction:正派小队"])
    index.add_tags("char:苏晚", ["char:苏晚", "faction:正派小队"])

    result = index.remove_ref("char:林澈")
    assert result["removed"] is True
    assert set(result["removed_tags"]) == {"char:林澈", "faction:正派小队"}

    # 共享标签仍在，只少了林澈
    assert index.tags_of("char:林澈") == []
    assert [r["ref"] for r in index.search(["faction:正派小队"])] == ["char:苏晚"]


def test_remove_ref_missing_returns_false(tmp_path):
    from shining_world.retrieval.tag_index import TagIndex

    index = TagIndex(tmp_path / "index.json")
    assert index.remove_ref("char:不存在")["removed"] is False
