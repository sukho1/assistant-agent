"""MCP Server for diary RAG search. Stdio transport, singleton model."""
import os
import sqlite3
import sys
import threading
import chromadb
from sentence_transformers import SentenceTransformer
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# Keep network requests offline so HuggingFace doesn't phone home on cache hits.
# Falls back to online if model isn't cached yet.
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# ── Singleton model ──
_model = None
_model_lock = threading.Lock()
_model_ready = threading.Event()


def _load_model() -> SentenceTransformer:
    """Actually load and warm-up the embedding model (may take 10-18s)."""
    print("[diary-rag] Loading embedding model...", file=sys.stderr)
    try:
        model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)
    except Exception:
        print("[diary-rag] Model not cached, downloading...", file=sys.stderr)
        model = SentenceTransformer(config.EMBED_MODEL_NAME)
    model.encode(["warm-up"], normalize_embeddings=True, show_progress_bar=False)
    print("[diary-rag] Model ready.", file=sys.stderr)
    return model


def get_model() -> SentenceTransformer:
    """Return the model, blocking until background pre-warm finishes if needed."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = _load_model()
    _model_ready.set()
    return _model


def _prewarm_background() -> None:
    """Load model in a background thread so first search_diary call is fast."""
    print("[diary-rag] Background pre-warm started...", file=sys.stderr)
    get_model()


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
    model = get_model()

    # 1. Encode query
    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False
    )

    # 2. ChromaDB search with oversampling
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = client.get_collection(config.COLLECTION_NAME)

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


if __name__ == '__main__':
    print("[diary-rag] MCP server starting...", file=sys.stderr)
    print(f"[diary-rag] ChromaDB: {config.CHROMA_DIR}", file=sys.stderr)
    print(f"[diary-rag] SQLite: {config.DB_PATH}", file=sys.stderr)
    # Start background model pre-warm — server answers MCP handshake immediately,
    # and the model loads in parallel so first search_diary() is fast.
    threading.Thread(target=_prewarm_background, daemon=True).start()
    mcp.run(transport="stdio")
