"""一致性校验：防吃书、防 OOC、防时序冲突。"""

from __future__ import annotations

from .checker import ConsistencyChecker, Violation

__all__ = ["ConsistencyChecker", "Violation"]
