"""``python -m shining_world`` → 默认走 SSE。"""

from __future__ import annotations

import sys

from .entry.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
