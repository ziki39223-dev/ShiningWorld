"""标签索引与向量库测试。"""

from __future__ import annotations

import pytest

from shining_world.common.errors import ToolError
from shining_world.retrieval.engine import RetrievalEngine
from shining_world.retrieval.tag_index import TagIndex, validate_tags
from shining_world.retrieval.vector_store import VectorStore, cosine, embed


def test_validate_tags_accepts_known_prefix():
    assert validate_tags(["char:林澈", "loc:雾港", "char:林澈"]) == ["char:林澈", "loc:雾港"]


@pytest.mark.parametrize("bad", ["林澈", "npc:张三", "char:", "char:林 澈"])
def test_validate_tags_rejects_bad(bad: str):
    with pytest.raises(ToolError):
        validate_tags([bad])


def test_tag_index_intersection_and_union(tmp_path):
    index = TagIndex(tmp_path / "index.json")
    index.add_tags("char:林澈", ["char:林澈", "faction:正派小队"], {"faction": "正派小队"})
    index.add_tags("loc:雾港", ["loc:雾港", "faction:正派小队"], {"faction": "正派小队"})

    both = index.search(["char:林澈", "faction:正派小队"], match_all=True)
    assert [r["ref"] for r in both] == ["char:林澈"]

    either = index.search(["char:林澈", "loc:雾港"], match_all=False)
    assert {r["ref"] for r in either} == {"char:林澈", "loc:雾港"}


def test_tag_index_remove_drops_empty_tag(tmp_path):
    index = TagIndex(tmp_path / "index.json")
    index.add_tags("char:林澈", ["char:林澈"])
    index.remove_tags("char:林澈", ["char:林澈"])
    assert index.all_tags() == {}
    assert index.tags_of("char:林澈") == []


def test_embed_is_normalized_and_similarity_is_sane():
    a = embed("雾港的钟声在夜里响起", dim=128)
    b = embed("夜里雾港响起钟声", dim=128)
    c = embed("边疆战事吃紧", dim=128)
    assert pytest.approx(sum(a.values()), abs=1e-6) == 1.0
    assert cosine(a, b) > cosine(a, c)


def test_engine_prefers_tags_then_falls_back(tmp_path):
    tags = TagIndex(tmp_path / "index.json")
    vectors = VectorStore(tmp_path / "vec.json", dim=128)

    from shining_world.config.settings import RetrievalConfig

    engine = RetrievalEngine(tags, vectors, RetrievalConfig(vector_dim=128, vector_top_k=3))
    engine.index_document("char:林澈", "林澈是雾港的年轻队长，行事谨慎", ["char:林澈"], faction="正派小队")
    engine.index_document("loc:雾港", "雾港常年有雾，夜间封锁城门", ["loc:雾港"], faction="")

    hit = engine.search(["char:林澈"], "谁会守在城门")
    assert hit["strategy"] == "tag"
    assert hit["hits"][0]["ref"] == "char:林澈"

    miss = engine.search(["char:不存在"], "夜间封锁的港口")
    assert miss["strategy"] == "vector"
    assert miss["hits"], "向量兜底应召回内容"


def test_engine_faction_scope_hides_other_faction(tmp_path):
    tags = TagIndex(tmp_path / "index.json")
    vectors = VectorStore(tmp_path / "vec.json", dim=64)
    from shining_world.config.settings import RetrievalConfig

    engine = RetrievalEngine(tags, vectors, RetrievalConfig(vector_dim=64))
    engine.index_document("char:密探甲", "密探甲只向暗流汇报", ["char:密探甲"], faction="暗流")

    visible = engine.search(["char:密探甲"], "", faction_scope={"正派小队"})
    assert visible["hits"] == []
