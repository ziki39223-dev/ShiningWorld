"""服务装配：把配置、检索、世界观、支线、记忆、校验、推演组装成单一核心服务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config.loader import load_settings
from ..config.settings import AppSettings
from ..consistency.checker import ConsistencyChecker
from ..narrative.context import ContextBuilder
from ..narrative.distiller import CharacterDistiller
from ..narrative.engine import NarrativeEngine
from ..narrative.prompts import PromptLibrary
from ..providers.provider_manager import ProviderManager, build_manager
from ..retrieval.engine import RetrievalEngine
from ..retrieval.tag_index import TagIndex
from ..retrieval.vector_store import VectorStore
from ..streams.manager import StreamManager, build_stream_manager
from ..streams.snapshot import SnapshotManager
from ..world.pools import WorldBible, build_world_bible


@dataclass(slots=True)
class ShiningWorldService:
    """唯一核心服务的聚合根。"""

    settings: AppSettings
    manager: ProviderManager
    retrieval: RetrievalEngine
    world: WorldBible
    streams: StreamManager
    snapshots: SnapshotManager
    checker: ConsistencyChecker
    distiller: CharacterDistiller
    builder: ContextBuilder
    engine: NarrativeEngine
    prompts: PromptLibrary

    def stats(self) -> dict[str, Any]:
        return {
            "workspace": str(self.settings.workspace_root),
            "streams": len(self.streams.list()),
            "providers": len(self.settings.providers)
            + (1 if self.settings.use_mock_provider else 0),
            "world": self.world.stats(),
        }


def build_service(config_path: str) -> ShiningWorldService:
    """从 config.yaml 装配完整服务。"""
    settings = load_settings(config_path)
    return build_service_from_settings(settings)


def build_service_from_settings(settings: AppSettings) -> ShiningWorldService:
    settings.ensure_dirs()

    tag_index = TagIndex(settings.world_dir / "index.json")
    vector_store = VectorStore(settings.vector_dir / "index.json", dim=settings.retrieval.vector_dim)
    retrieval = RetrievalEngine(tag_index, vector_store, settings.retrieval)

    world = build_world_bible(settings, retrieval)
    streams = build_stream_manager(settings)
    snapshots = SnapshotManager(settings, streams, world.proposals)

    manager = build_manager(settings)
    prompts = PromptLibrary()
    checker = ConsistencyChecker(world)
    distiller = CharacterDistiller(manager, prompts)
    builder = ContextBuilder(world, streams, snapshots, retrieval)
    engine = NarrativeEngine(
        world=world,
        streams=streams,
        snapshots=snapshots,
        retrieval_builder=builder,
        manager=manager,
        checker=checker,
        distiller=distiller,
        prompts=prompts,
    )

    if settings.mainline_outline and world.plot.mainline() is None:
        world.plot.set_mainline_outline(settings.mainline_outline)

    return ShiningWorldService(
        settings=settings,
        manager=manager,
        retrieval=retrieval,
        world=world,
        streams=streams,
        snapshots=snapshots,
        checker=checker,
        distiller=distiller,
        builder=builder,
        engine=engine,
        prompts=prompts,
    )


def persist_indexes(service: ShiningWorldService) -> None:
    """把内存索引刷盘（退出前调用）。"""
    service.retrieval.tags.save()
    service.retrieval.vectors.save()
