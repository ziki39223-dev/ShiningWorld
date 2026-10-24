"""统一错误码与工具返回信封。

所有 MCP 工具都返回 ``{"ok": bool, ...}`` 结构，绝不让客户端看到裸异常。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """稳定的错误码，DSH 面板可据此做提示。"""

    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONSISTENCY_VIOLATION = "CONSISTENCY_VIOLATION"
    IO_ERROR = "IO_ERROR"
    INTERNAL = "INTERNAL"


class ToolError(Exception):
    """业务错误：带错误码与细节，由服务层转成信封。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def ok(**payload: Any) -> dict[str, Any]:
    """成功信封。"""
    return {"ok": True, **payload}


def fail(error: ToolError) -> dict[str, Any]:
    """失败信封。"""
    return {
        "ok": False,
        "error": {
            "code": str(error.code),
            "message": error.message,
            "detail": error.detail,
        },
    }
