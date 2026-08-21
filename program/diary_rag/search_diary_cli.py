"""Standalone CLI fallback for search_diary.

The MCP server is the preferred path. When the MCP tool is not available,
run this script directly; it starts the same pre-warm routine and prints
search results as JSON.

--output <path> writes full results to a UTF-8 file in a multi-line readable
format (one field per line, content wrapped) so the complete diary text can
be read back without truncation. Without --output, compact JSON goes to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import server


def _wrap(text: str, width: int = 1000) -> str:
    """Wrap long text by width to survive line-based read truncation."""
    if len(text) <= width:
        return text
    return "\n".join(text[i : i + width] for i in range(0, len(text), width))


def _write_text(hits: dict, path: str, title: str = "", mode: str = "w") -> None:
    lines = []
    if title:
        lines.append(f"########## query: {title} ##########")
        lines.append("")
    for i, r in enumerate(hits.get("parents", []), 1):
        lines.append(f"===== [全文{i}] {r.get('date', '')} {r.get('title', '')} ({r.get('char_count', 0)}字, {r.get('type', '')})")
        lines.append(f"id: {r.get('id', '')}")
        lines.append("")
        lines.append(_wrap(r.get("content", "")))
        lines.append("")
    for i, s in enumerate(hits.get("slices", []), 1):
        lines.append(f"----- [切片{i}] {s.get('date', '')} {s.get('title', '')} | {s.get('sub_title', '')}")
        lines.append(f"id: {s.get('id', '')}  parent: {s.get('parent_id', '')}")
        lines.append(_wrap(s.get("content", "")))
        lines.append("")
    with open(path, mode, encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="", help="单 query（向后兼容）")
    parser.add_argument("--query", dest="queries", action="append", help="批量 query，可多次指定；一次预热跑完所有 query")
    parser.add_argument("top_k", nargs="?", type=int, default=20)
    parser.add_argument("--output", default=None, help="write full results to this UTF-8 file")
    args = parser.parse_args()

    if args.queries:
        queries = args.queries
    elif args.query:
        queries = [args.query]
    else:
        print(json.dumps([{"status": "error", "message": "缺少 query。"}], ensure_ascii=False))
        return 1

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

    batch = [{"query": q, "hits": server.search_diary(q, top_k=args.top_k)} for q in queries]

    if args.output:
        for idx, entry in enumerate(batch):
            _write_text(entry["hits"], args.output, title=entry["query"], mode="w" if idx == 0 else "a")
        print(json.dumps({
            "status": "ok",
            "count": sum(len(e["hits"].get("parents", [])) for e in batch),
            "output_file": args.output,
        }, ensure_ascii=False))
    else:
        print(json.dumps(batch, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
