"""世界观池子：剧情池 / 地图池 / 人文池 / 人物池 + 变更提案审批。"""

from __future__ import annotations

from .character_sheet import CHARACTER_SHEET_TEMPLATE, build_character_sheet, validate_character_sheet
from .pools import (
    CharacterPool,
    CulturePool,
    MapPool,
    PlotPool,
    ProposalQueue,
    WorldBible,
    build_world_bible,
)

__all__ = [
    "CHARACTER_SHEET_TEMPLATE",
    "build_character_sheet",
    "validate_character_sheet",
    "CharacterPool",
    "CulturePool",
    "MapPool",
    "PlotPool",
    "ProposalQueue",
    "WorldBible",
    "build_world_bible",
]
