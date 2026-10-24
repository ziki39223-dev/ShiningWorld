"""MCP Server 装配：注册全部工具、配置生命周期。"""

from __future__ import annotations

from .app import SERVER_NAME, SERVER_VERSION, build_server, register_tools

__all__ = ["SERVER_NAME", "SERVER_VERSION", "build_server", "register_tools"]
