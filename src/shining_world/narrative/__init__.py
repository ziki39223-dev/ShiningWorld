"""叙事核心：上下文拼装、Prompt 模板、角色蒸馏、单步推演。"""

from __future__ import annotations

from .context import ContextBuilder, NarrativeContext
from .distiller import CharacterDistiller
from .engine import NarrativeEngine, StepResult
from .prompts import PromptLibrary

__all__ = [
    "ContextBuilder",
    "NarrativeContext",
    "CharacterDistiller",
    "NarrativeEngine",
    "StepResult",
    "PromptLibrary",
]
