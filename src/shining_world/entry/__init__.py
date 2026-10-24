"""进程入口：stdio（DSH 本地子进程）/ SSE（远程连接）/ 自检。"""

from .cli import main, run_selfcheck, run_sse, run_stdio

__all__ = ["main", "run_selfcheck", "run_sse", "run_stdio"]
