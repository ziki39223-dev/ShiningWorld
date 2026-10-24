"""工具层：把服务能力包装成「入参校验 → 服务调用 → 信封」的纯函数。"""

from __future__ import annotations

from .facade import ToolFacade

__all__ = ["ToolFacade"]
