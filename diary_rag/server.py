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


WARMUP_TIMEOUT_S = 75  # > cold-Defender worst case ~55s, < MCP transport timeout 120s
_warmup_restarts = 0
MAX_WARMUP_RESTARTS = 2  # max warmup thread restarts before giving up

_warmup_error: str | None = None  # set when warmup thread fails — search_diary returns error immediately
_warmup_model_done_at: float | None = None  # actual timestamp when model load finished (for dynamic eta)
_warmup_generation: int = 0  # incremented on restart; old threads discard results


def _load_model():
    """Load the embedding model from local cache (~23s import + ~4s weights, or ~45s with Defender cold).

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
    global _warmup_restarts, _warmup_started_at, _warmup_stage, _warmup_generation, _warmup_error
    # Pre-warm runs in background thread.  If it hasn't finished, return
    # warming_up status immediately (no blocking) so the client can see
    # stage + elapsed time and decide how long to wait before retrying.
    #
    # Two parallel tool calls both get a fast non-blocking response — no
    # stdio queueing, no MCP timeout.
    if not _prewarm_done.is_set():
        elapsed = time.time() - _warmup_started_at if _warmup_started_at else 0

        # P0: warmup thread died silently (model load exception →
        # _prewarm_background returned early without setting _warmup_error).
        # Report error immediately instead of returning warming_up forever.
        if _warmup_error is not None:
            return [{"status": "error",
                     "stage": _warmup_stage,
                     "elapsed_s": round(elapsed, 1),
                     "message": f"预热失败: {_warmup_error}"}]

        # P1: timeout — cold start with Windows Defender takes ~55s;
        # WARMUP_TIMEOUT_S (75s) is above that but below MCP transport
        # timeout (120s).  If we reach this, the background thread is stuck
        # (not just slow) — restart it.
        if elapsed > WARMUP_TIMEOUT_S:
            if _warmup_restarts < MAX_WARMUP_RESTARTS:
                _warmup_restarts += 1
                old_elapsed = elapsed
                _warmup_generation += 1
                _warmup_error = None  # clear previous error on restart
                _warmup_started_at = time.time()
                _warmup_stage = "init"
                elapsed = 0
                gen = _warmup_generation
                print(f"[diary-rag] Warmup timed out after {old_elapsed:.0f}s, restarting "
                      f"(attempt {_warmup_restarts}/{MAX_WARMUP_RESTARTS}, gen={gen})...",
                      file=sys.stderr, flush=True)
                threading.Thread(target=_prewarm_background, daemon=True,
                                 kwargs={"generation": gen}).start()
                # fall through to warming_up response below
            else:
                return [{"status": "error",
                         "stage": _warmup_stage,
                         "elapsed_s": round(elapsed, 1),
                         "message": f"预热超时（{_warmup_stage}阶段卡了{elapsed:.0f}秒）。"
                                    f"已重启{_warmup_restarts}次仍失败。"
                                    f"可能原因：模型缓存损坏、ChromaDB数据损坏、或系统资源不足。"
                                    f"诊断：1) python -c \"from sentence_transformers import SentenceTransformer; SentenceTransformer('{config.EMBED_MODEL_NAME}', local_files_only=True)\" 测试模型加载 "
                                    f"2) 检查HuggingFace缓存 ~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/ 下的文件完整性 "
                                    f"3) 查看MCP进程stderr输出的traceback定位具体原因"}]

        # P0b: eta_s — conservative estimate covering cold Windows Defender.
        # Measured on this machine:
        #   Cold (Defender first scan): model ~45-50s, chromadb ~5s → ~55s total
        #   Warm (Defender verdict cached): model ~28s, chromadb ~4.5s → ~33s
        # Use cold numbers as fallback so eta doesn't lie on first launch of day.
        MODEL_FALLBACK_S = 50   # model import+load with Defender cold
        CHROMADB_FALLBACK_S = 5  # chromadb import+init
        TOTAL_FALLBACK_S = MODEL_FALLBACK_S + CHROMADB_FALLBACK_S  # 55

        if _warmup_stage == "model":
            eta_s = max(MODEL_FALLBACK_S - elapsed, 2)
        elif _warmup_stage == "chromadb":
            # Use actual model load time if available, otherwise fallback
            if _warmup_model_done_at is not None:
                model_actual = _warmup_model_done_at - _warmup_started_at
                chromadb_done_at_est = model_actual + CHROMADB_FALLBACK_S
                eta_s = max(chromadb_done_at_est - elapsed, 1)
            else:
                eta_s = max(TOTAL_FALLBACK_S - elapsed, 2)
        else:  # "init"
            eta_s = max(TOTAL_FALLBACK_S - elapsed, 3)

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


def _prewarm_background(generation: int = 0) -> None:
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
    global _warmup_error, _warmup_model_done_at

    import time
    t_start = time.time()
    _warmup_started_at = t_start
    _warmup_stage = "model"

    print("[diary-rag] Background pre-warm started (model + ChromaDB)...",
          file=sys.stderr, flush=True)

    # 1. Embedding model
    _t0 = time.time()
    try:
        import torch as _torch  # noqa: F811
        print(f"[diary-rag] import torch: {time.time() - _t0:.1f}s",
              file=sys.stderr, flush=True)
        _t1 = time.time()
        import transformers as _tf  # noqa: F811
        print(f"[diary-rag] import transformers: {time.time() - _t1:.1f}s",
              file=sys.stderr, flush=True)
        _t2 = time.time()
        get_model()
        print(f"[diary-rag] sentence_transformers + model load: {time.time() - _t2:.1f}s",
              file=sys.stderr, flush=True)
    except Exception as e:
        _warmup_error = f"Model load failed: {e}"
        print(f"[diary-rag] Background model load failed: {e}",
              file=sys.stderr, flush=True)
        return
    t_model = time.time()
    _warmup_model_done_at = t_model
    _warmup_stage = "chromadb"
    print(f"[diary-rag] Model loaded ({t_model - t_start:.0f}s total).",
          file=sys.stderr, flush=True)

    # 2. ChromaDB — slow import happens OUTSIDE the lock so search_diary()
    #    never blocks waiting for this thread.  Only the final pointer
    #    assignment is guarded.
    _tc0 = time.time()
    try:
        import chromadb  # noqa: F811
        print(f"[diary-rag] import chromadb: {time.time() - _tc0:.1f}s",
              file=sys.stderr, flush=True)
        _tc1 = time.time()
        client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        collection = client.get_collection(config.COLLECTION_NAME)
        print(f"[diary-rag] ChromaDB init + get_collection: {time.time() - _tc1:.1f}s",
              file=sys.stderr, flush=True)
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

    # Guard: if this thread was superseded by a restart, don't corrupt state.
    if generation != _warmup_generation:
        print(f"[diary-rag] Warmup thread gen={generation} stale "
              f"(current={_warmup_generation}), discarding.",
              file=sys.stderr, flush=True)
        return
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
    #   - Cold start (Defender first scan): model ~45-50s + ChromaDB ~5s ≈ 55s
    #   - Warm start (Defender verdict cached): model ~28s + ChromaDB ~4.5s ≈ 33s
    #   - MCP transport timeout (120s in .mcp.json) covers worst case
    threading.Thread(target=_prewarm_background, kwargs={"generation": 0},
                     daemon=True).start()
    mcp.run(transport="stdio")
