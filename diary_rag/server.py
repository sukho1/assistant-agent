"""MCP Server for diary RAG search. Stdio transport, singleton model."""
from __future__ import annotations

import os
import sqlite3
import sys
import threading
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# Keep network requests offline so HuggingFace doesn't phone home on cache hits.
# Falls back to online if model isn't cached yet.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# ── Singleton model + ChromaDB ──
_model = None
_model_lock = threading.Lock()

_chroma_client = None
_chroma_collection = None
_chroma_lock = threading.Lock()

_prewarm_done = threading.Event()


def _load_model():
    """Actually load and warm-up the embedding model (~4s on CPU)."""
    from sentence_transformers import SentenceTransformer  # lazy import, ~22s on first load

    print("[diary-rag] Loading embedding model...", file=sys.stderr, flush=True)
    try:
        model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)
    except Exception:
        print("[diary-rag] Model not cached, downloading...", file=sys.stderr, flush=True)
        model = SentenceTransformer(config.EMBED_MODEL_NAME)
    model.encode(["warm-up"], normalize_embeddings=True, show_progress_bar=False)
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
    # If background pre-warm hasn't completed AND model hasn't even loaded yet,
    # wait briefly (5s cap) for the background thread.  This absorbs most
    # mid-load calls without forcing a client retry.  If prewarm still isn't
    # done after 5s, return warming_up — the client retries a few seconds later.
    #
    # If the model IS loaded (even if _prewarm_done isn't set — e.g. bg thread
    # is still loading ChromaDB), proceed: the inline fallback below handles
    # ChromaDB init safely (import + init outside _chroma_lock, no deadlock).
    if not _prewarm_done.is_set() and _model is None:
        # Wait briefly for the background thread. Caps at 5s to stay well
        # within the MCP timeout.  If prewarm finishes while we wait, proceed
        # immediately — no retry needed.
        if _prewarm_done.wait(timeout=5.0):
            pass  # prewarm completed — fall through to normal search
        else:
            return [{"status": "warming_up",
                     "message": "模型仍在加载中，请稍后重试（首次加载约需 20-30 秒）"}]

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

    IMPORTANT: slow imports (chromadb) happen OUTSIDE the lock, so
    search_diary() doesn't block if it races with this thread.  Only
    the final pointer assignments go under _chroma_lock."""
    global _chroma_client, _chroma_collection

    import time
    t_start = time.time()

    print("[diary-rag] Background pre-warm started (model + ChromaDB)...",
          file=sys.stderr, flush=True)

    # 1. Embedding model (~14s import + ~4s load on first run)
    get_model()
    t_model = time.time()
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
