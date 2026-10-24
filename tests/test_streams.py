"""支线状态机 + 快照记忆测试。"""

from __future__ import annotations

import pytest

from shining_world.common.errors import ToolError
from shining_world.streams.manager import StreamManager


def test_create_stream_writes_expected_files(service):
    record = service.streams.create("正派小队视角", faction="正派小队", cell=1)
    base = service.streams.dir_of(record)

    assert (base / "manifest.json").exists()
    assert (base / "status.json").exists()
    assert (base / "content.log").exists()
    assert (base / "snapshot").is_dir()
    assert (base / "history").is_dir()
    assert record.status == "cooldown"


def test_duplicate_name_is_allowed_but_duplicate_id_rejected(service):
    first = service.streams.create("同名")
    with pytest.raises(ToolError):
        service.streams.create("另一个", stream_id=first.stream_id)


def test_get_by_name_and_missing(service):
    service.streams.create("暗流伏笔线")
    assert service.streams.get("暗流伏笔线").name == "暗流伏笔线"
    with pytest.raises(ToolError):
        service.streams.get("不存在的支线")


def test_append_and_incremental_read(service):
    record = service.streams.create("主线大纲")
    service.streams.append_content(record.stream_id, "第一段剧情。")
    service.streams.append_content(record.stream_id, "第二段剧情。")

    full = service.streams.read_content(record.stream_id)
    assert "第一段" in full["content"] and "第二段" in full["content"]

    tail = service.streams.read_content(record.stream_id, since_chars=len("第一段剧情。\n"))
    assert tail["content"].startswith("第二段")
    assert tail["total_chars"] > tail["returned_chars"]


def test_pause_resume_and_due(service):
    record = service.streams.create("守卫/城防视角", cooldown_s=0)
    assert [r.stream_id for r in service.streams.due_streams()] == [record.stream_id]

    service.streams.pause(record.stream_id)
    assert service.streams.due_streams() == []

    service.streams.resume(record.stream_id)
    assert service.streams.due_streams() != []


def test_pause_all_and_resume_all(service):
    service.streams.create("A", cooldown_s=0)
    service.streams.create("B", cooldown_s=0)

    service.streams.pause_all()
    assert all(r.status == "paused" for r in service.streams.list())
    assert service.streams.due_streams() == []

    service.streams.resume_all()
    assert len(service.streams.due_streams()) == 2


def test_status_persists_across_manager_reload(service, settings):
    record = service.streams.create("持久化测试")
    service.streams.append_content(record.stream_id, "一次推进。")

    reloaded = StreamManager(settings)
    again = reloaded.get(record.stream_id)
    assert again.step_count == 1
    assert again.total_chars > 0


def test_snapshot_proposal_and_approval(service):
    record = service.streams.create("快照支线")
    service.streams.append_content(record.stream_id, "长" * 300)

    proposal = service.snapshots.create_proposal(
        record.stream_id,
        summary="主角团拿到证物，尚未出城。",
        key_facts=["证物在队长手中", "城门已封锁"],
    )
    snapshot_id = proposal["snapshot"]["snapshot_id"]
    assert proposal["proposal"]["status"] == "pending"

    approved = service.snapshots.approve(record.stream_id, snapshot_id, note="确认归档")
    assert approved["status"] == "approved"
    assert approved["context_policy"]["drop_before_chars"] >= 0

    with pytest.raises(ToolError):
        service.snapshots.approve(record.stream_id, snapshot_id)


def test_should_snapshot_honours_threshold(service):
    record = service.streams.create("阈值支线")
    service.streams.append_content(record.stream_id, "字" * 250)  # 夹具阈值 200
    assert service.snapshots.should_snapshot(record.stream_id) is True

    proposal = service.snapshots.create_proposal(record.stream_id, summary="摘要")
    service.snapshots.approve(record.stream_id, proposal["snapshot"]["snapshot_id"])
    assert service.snapshots.should_snapshot(record.stream_id) is False


def test_memory_context_uses_latest_snapshot(service):
    record = service.streams.create("记忆支线")
    service.streams.append_content(record.stream_id, "近" * 100)

    proposal = service.snapshots.create_proposal(
        record.stream_id,
        summary="旧摘要",
        key_facts=["事实A"],
    )
    service.snapshots.approve(record.stream_id, proposal["snapshot"]["snapshot_id"])

    context = service.snapshots.build_memory_context(record.stream_id)
    assert context["snapshot_count"] == 1
    assert "旧摘要" in context["snapshot_context"]
    assert "事实A" in context["snapshot_context"]
