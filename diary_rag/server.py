"""MCP Server for diary RAG search. Stdio transport, singleton model."""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
import time
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# Keep network requests offline — model is pre-cached, no download fallback.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# Disable tqdm in stdio MCP context — tqdm detects the asyncio event loop
# from mcp.run() and switches to tqdm_asyncio, which crashes with
# "ValueError: I/O operation on closed file" because stdout is owned by the
# MCP transport, not a real terminal.
os.environ.setdefault("TQDM_DISABLE", "1")

# ── Singleton model + ChromaDB ──
_model = None
_model_lock = threading.Lock()

_chroma_client = None
_chroma_collection = None
_chroma_lock = threading.Lock()

_prewarm_done = threading.Event()
_warmup_stage = "init"  # "model" | "chromadb" | "done"
_warmup_started_at: float | None = None


WARMUP_TIMEOUT_S = 60  # if pre-warm exceeds this, search_diary reports error
_warmup_restarts = 0
MAX_WARMUP_RESTARTS = 2  # max warmup thread restarts before giving up


def _load_model():
    """Load the embedding model from local cache (~15s import + ~0.3s weights).

    P0a: Model must be pre-cached (BAAI/bge-small-zh-v1.5).  No network
    fallback — downloading would hang indefinitely on slow Chinese networks
    and the client has no way to distinguish "downloading" from "loading".
    If the model isn't cached, fail fast with a clear error so the operator
    can pre-download it once.
    """
    import traceback
    from sentence_transformers import SentenceTransformer  # lazy import, ~15s on first load

    print("[diary-rag] Loading embedding model from cache...", file=sys.stderr, flush=True)
    try:
        model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)
        model.encode(["warm-up"], normalize_embeddings=True, show_progress_bar=False)
    except Exception as e:
        print(f"[diary-rag] Model load FAILED: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        raise
    print("[diary-rag] Model ready.", file=sys.stderr, flush=True)
    return model


def get_model():
    """Return the model, loading it on first access if needed.

    Does NOT set _prewarm_done — that's the background thread's job,
    because "done" means both model + ChromaDB are hot."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = _load_model()
    return _model


# ── Session state ──
_returned_ids: set = set()


# ── MCP Server ──
mcp = FastMCP("diary-rag")


@mcp.tool()
def search_diary(query: str, top_k: int = 5) -> list:
    """Search diary entries by semantic similarity.

    Args:
        query: Search query in natural language or keywords.
        top_k: Maximum number of parent blocks to return (default 5).

    Returns:
        List of parent blocks with date, title, type, and full content.
    """
    global _warmup_restarts, _warmup_started_at, _warmup_stage
    # Pre-warm runs in background thread.  If it hasn't finished, return
    # warming_up status immediately (no blocking) so the client can see
    # stage + elapsed time and decide how long to wait before retrying.
    #
    # Two parallel tool calls both get a fast non-blocking response — no
    # stdio queueing, no MCP timeout.
    if not _prewarm_done.is_set():
        elapsed = time.time() - _warmup_started_at if _warmup_started_at else 0

        # P1: timeout — pre-warm stuck > 60s is abnormal (model import ~15s,
        # ChromaDB ~4s, total ~20s).  The background thread likely died
        # (model load exception → _prewarm_background returned early).
        # Restart it instead of giving up immediately.
        if elapsed > WARMUP_TIMEOUT_S:
            if _warmup_restarts < MAX_WARMUP_RESTARTS:
                _warmup_restarts += 1
                old_elapsed = elapsed
                _warmup_started_at = time.time()
                _warmup_stage = "init"
                elapsed = 0
                print(f"[diary-rag] Warmup timed out after {old_elapsed:.0f}s, restarting "
                      f"(attempt {_warmup_restarts}/{MAX_WARMUP_RESTARTS})...",
                      file=sys.stderr, flush=True)
                threading.Thread(target=_prewarm_background, daemon=True).start()
                # fall through to warming_up response below
            else:
                return [{"status": "error",
                         "stage": _warmup_stage,
                         "elapsed_s": round(elapsed, 1),
                         "message": f"预热超时（{_warmup_stage}阶段卡了{elapsed:.0f}秒，预期<20s）。"
                                    f"已重启{_warmup_restarts}次仍失败。"
                                    f"可能原因：模型缓存损坏、ChromaDB数据损坏、或系统资源不足。"
                                    f"诊断：1) python -c \"from sentence_transformers import SentenceTransformer; SentenceTransformer('{config.EMBED_MODEL_NAME}', local_files_only=True)\" 测试模型加载 "
                                    f"2) 检查HuggingFace缓存 ~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/ 下的文件完整性 "
                                    f"3) 查看MCP进程stderr输出的traceback定位具体原因"}]

        # P0b: dynamic eta_s based on stage + elapsed instead of hardcoded 26.
        # Model stage: import ~15s + load ~0.3s ≈ 20s total from start.
        # ChromaDB stage: ~4s on top, so total ~24s from start.
        if _warmup_stage == "model":
            # model not even loaded yet — at least 20s total
            if elapsed < 20:
                eta_s = max(20 - elapsed, 3)
            else:
                eta_s = min(elapsed - 20 + 5, 15)
        elif _warmup_stage == "chromadb":
            # model done, chromadb ~4s more
            if elapsed < 24:
                eta_s = max(24 - elapsed, 2)
            else:
                eta_s = min(elapsed - 24 + 3, 10)
        else:
            if elapsed < 24:
                eta_s = max(24 - elapsed, 3)
            else:
                eta_s = min(elapsed - 24 + 5, 12)

        return [{"status": "warming_up",
                 "stage": _warmup_stage,
                 "elapsed_s": round(elapsed, 1),
                 "eta_s": round(eta_s, 1),
                 "message": f"后台预热中（{_warmup_stage}阶段，已过{elapsed:.0f}秒，预计还需{eta_s:.0f}秒）"}]

    model = get_model()  # returns immediately when _prewarm_done is set

    # 1. Encode query
    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False
    )

    # 2. ChromaDB search — client/collection pre-loaded by background thread
    #    Slow import + init MUST happen outside _chroma_lock to avoid deadlock
    #    with the background thread (Python import lock vs _chroma_lock).
    global _chroma_client, _chroma_collection

    needs_init = False
    with _chroma_lock:
        if _chroma_client is None:
            needs_init = True

    if needs_init:
        import chromadb  # outside lock — safe (matches background thread pattern)
        new_client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        new_collection = new_client.get_collection(config.COLLECTION_NAME)
        with _chroma_lock:
            # Double-check: bg thread might have finished while we were importing
            if _chroma_client is None:
                _chroma_client = new_client
                _chroma_collection = new_collection

    with _chroma_lock:
        client = _chroma_client
        collection = _chroma_collection

    fetch_k = top_k * config.OVERSAMPLE_FACTOR
    results = collection.query(
        query_embeddings=query_vec.tolist(),
        n_results=fetch_k
    )

    if not results["ids"] or not results["ids"][0]:
        return []

    # 3. Extract parent_ids, deduplicate, filter session returns
    seen_parents = set()
    parent_ids = []
    for meta in results["metadatas"][0]:
        pid = meta["parent_id"]
        if pid not in seen_parents and pid not in _returned_ids:
            seen_parents.add(pid)
            parent_ids.append(pid)
            if len(parent_ids) >= top_k:
                break

    # 4. Look up parent blocks from SQLite
    conn = sqlite3.connect(config.DB_PATH)
    placeholders = ','.join(['?' for _ in parent_ids])
    rows = conn.execute(
        f"SELECT id, date, title, block_type, char_count, content FROM parents WHERE id IN ({placeholders})",
        parent_ids
    ).fetchall()
    conn.close()

    # 5. Track returned IDs for session dedup
    for pid in parent_ids:
        _returned_ids.add(pid)

    # 6. Format results
    return [
        {
            "id": r[0],
            "date": r[1] or "",
            "title": r[2] or "",
            "type": r[3],
            "char_count": r[4],
            "content": r[5]
        }
        for r in rows
    ]


def _prewarm_background() -> None:
    """Eager-load embedding model + ChromaDB in background thread.

    Starts the moment the MCP server process launches — before the first
    user message, before the first tool call.  The MCP handshake returns
    fast (sub-2s) while this thread does the heavy lifting.

    Sets _warmup_stage / _warmup_started_at so search_diary() can return
    structured warming_up status without blocking.

    IMPORTANT: slow imports (chromadb) happen OUTSIDE the lock, so
    search_diary() doesn't block if it races with this thread.  Only
    the final pointer assignments go under _chroma_lock."""
    global _chroma_client, _chroma_collection, _warmup_stage, _warmup_started_at

    import time
    t_start = time.time()
    _warmup_started_at = t_start
    _warmup_stage = "model"

    print("[diary-rag] Background pre-warm started (model + ChromaDB)...",
          file=sys.stderr, flush=True)

    # 1. Embedding model (~14s import + ~4s load on first run)
    try:
        get_model()
    except Exception as e:
        print(f"[diary-rag] Background model load failed: {e}",
              file=sys.stderr, flush=True)
        # Don't set _prewarm_done — let search_diary report the error.
        # _warmup_stage stays "model" so the elapsed timer keeps running
        # and eventually triggers the >60s timeout path.
        return
    t_model = time.time()
    _warmup_stage = "chromadb"
    print(f"[diary-rag] Model loaded ({t_model - t_start:.0f}s).",
          file=sys.stderr, flush=True)

    # 2. ChromaDB — slow import happens OUTSIDE the lock so search_diary()
    #    never blocks waiting for this thread.  Only the final pointer
    #    assignment is guarded.
    try:
        import chromadb  # noqa: F811
        print("[diary-rag] Loading ChromaDB...", file=sys.stderr, flush=True)
        client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        collection = client.get_collection(config.COLLECTION_NAME)
        # Quick pointer assignment under lock — microseconds, not seconds
        with _chroma_lock:
            _chroma_client = client
            _chroma_collection = collection
        t_chroma = time.time()
        print(f"[diary-rag] ChromaDB ready ({t_chroma - t_model:.0f}s).",
              file=sys.stderr, flush=True)
    except Exception:
        print("[diary-rag] ChromaDB pre-load failed, will retry on first query.",
              file=sys.stderr, flush=True)

    _warmup_stage = "done"
    _prewarm_done.set()
    print(f"[diary-rag] Pre-warm complete — all deps hot ({time.time() - t_start:.0f}s total).",
          file=sys.stderr, flush=True)


if __name__ == '__main__':
    print("[diary-rag] MCP server starting...", file=sys.stderr, flush=True)
    print(f"[diary-rag] ChromaDB: {config.CHROMA_DIR}", file=sys.stderr, flush=True)
    print(f"[diary-rag] SQLite: {config.DB_PATH}", file=sys.stderr, flush=True)
    # Pre-warm the embedding model in a background thread:
    #   - MCP handshake completes in ~2s (no heavy imports during handshake)
    #   - sentence_transformers (~22s) + chromadb (~4s) load in parallel
    #   - When the warm-up search_diary call arrives, get_model() blocks until
    #     the background thread finishes loading (at most ~22s from start)
    #   - MCP timeout (60s) covers worst case where warm-up call hits immediately
    threading.Thread(target=_prewarm_background, daemon=True).start()
    mcp.run(transport="stdio")
