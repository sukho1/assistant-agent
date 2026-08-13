"""Standalone CLI fallback for search_diary.

The MCP server is the preferred path. When the MCP tool is not available,
run this script directly; it starts the same pre-warm routine and prints
search results as JSON.
"""

from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    top_k = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    if not server._prewarm_done.is_set():
        server._prewarm_background()
        deadline = time.time() + server.WARMUP_TIMEOUT_S
        while not server._prewarm_done.is_set() and time.time() < deadline:
            time.sleep(0.2)

    if not server._prewarm_done.is_set():
        print(
            json.dumps(
                [{
                    "status": "error",
                    "stage": server._warmup_stage,
                    "message": f"预热超时（{server._warmup_stage}）。",
                }],
                ensure_ascii=False,
            )
        )
        return 1

    results = server.search_diary(query, top_k=top_k)
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
