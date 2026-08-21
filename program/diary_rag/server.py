"""MCP Server for diary RAG search. Stdio transport, singleton model.

Fast path: loads the pre-exported BGE ONNX model with onnxruntime and
tokenizers, avoiding the 30-55s PyTorch/sentence-transformers startup.
If the ONNX files or runtime libraries are missing, it falls back to
SentenceTransformer so the server still starts.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
import sys
import threading
import time
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

# mcp 1.x Settings.lifespan 的泛型前向引用在 pydantic-settings 2.15 下会触发
# IncompleteFieldDefinitionWarning；model_rebuild() 在实例化前解析注解，根治该警告。
from mcp.server.fastmcp.server import Settings as _McpSettings

_McpSettings.model_rebuild()

# Keep network requests offline — model is pre-cached, no download fallback.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
# Disable tqdm in stdio MCP context.
os.environ.setdefault("TQDM_DISABLE", "1")


class OnnxEmbedder:
    """Small BGE encoder using the exported ONNX backbone and tokenizer.json."""

    def __init__(self, tokenizer, session):
        import numpy as np

        self._tokenizer = tokenizer
        self._session = session
        self._np = np
        self._run_lock = threading.Lock()

    def encode(
        self,
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        batch_size=None,
    ):
        np = self._np
        vectors = []

        for text in texts:
            enc = self._tokenizer.encode(text)
            ids = list(enc.ids)
            mask = list(getattr(enc, "attention_mask", None) or [1] * len(ids))
            type_ids = list(getattr(enc, "type_ids", None) or [0] * len(ids))

            if not ids:
                unk = self._tokenizer.token_to_id("[UNK]") or 100
                ids, mask, type_ids = [unk], [1], [0]

            ids = ids[: config.EMBED_MAX_TOKENS]
            mask = mask[: config.EMBED_MAX_TOKENS]
            type_ids = type_ids[: config.EMBED_MAX_TOKENS]

            feed = {
                "input_ids": np.asarray([ids], dtype=np.int64),
                "attention_mask": np.asarray([mask], dtype=np.int64),
                "token_type_ids": np.asarray([type_ids], dtype=np.int64),
            }

            # onnxruntime sessions are not fully thread-safe for concurrent run()
            # calls, so serialize the tiny inference step.
            with self._run_lock:
                last_hidden = self._session.run(None, feed)[0]

            # BGE-small-zh-v1.5 uses CLS pooling, then L2 normalization.
            vector = np.asarray(last_hidden[0, 0, :], dtype=np.float32)
            if normalize_embeddings:
                norm = float(np.linalg.norm(vector))
                if norm > 1e-12:
                    vector = vector / norm
            vectors.append(vector)

        return np.asarray(vectors, dtype=np.float32)


# ── Singleton model + ChromaDB ──
_model = None
_model_lock = threading.Lock()

_chroma_client = None
_chroma_collection = None
_chroma_lock = threading.Lock()

_prewarm_done = threading.Event()
_warmup_stage = "init"  # "model" | "chromadb" | "done"
_warmup_started_at: float | None = None

WARMUP_TIMEOUT_S = 75
_warmup_restarts = 0
MAX_WARMUP_RESTARTS = 2

_warmup_error: str | None = None
_warmup_model_done_at: float | None = None
_warmup_generation: int = 0


def _open_chroma():
    """Open the Chroma client and collection (call under _chroma_startup_lock)."""
    import chromadb

    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = client.get_collection(config.COLLECTION_NAME)
    return client, collection


@contextlib.contextmanager
def _chroma_startup_lock():
    """Serialize ChromaDB initialization across server processes.

    Two servers (e.g. ZCode and Codex sessions) opening the same persistent
    directory at once contend on the sqlite lock during startup, which was
    observed to stretch the pre-warm from ~8s to 20s+. The lock is
    best-effort: after a 30s deadline we proceed without it, and a stale lock
    file (holder crashed) is reclaimed after 60s.
    """
    path = os.path.join(config.DATA_DIR, ".chroma-init.lock")
    deadline = time.time() + 30
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii"))
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > 60:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.time() > deadline:
                break
            time.sleep(0.2)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _load_onnx_model():
    """Load the exported BGE ONNX model and fast tokenizer.

    Raises if the runtime files or libraries are unavailable; _load_model()
    then falls back to SentenceTransformer.
    """
    import numpy as np
    import onnxruntime as ort
    from tokenizers import Tokenizer

    if not os.path.isfile(config.ONNX_MODEL_PATH):
        raise FileNotFoundError(f"missing ONNX model: {config.ONNX_MODEL_PATH}")
    if not os.path.isfile(config.TOKENIZER_PATH):
        raise FileNotFoundError(f"missing tokenizer: {config.TOKENIZER_PATH}")

    tokenizer = Tokenizer.from_file(config.TOKENIZER_PATH)
    tokenizer.enable_truncation(max_length=config.EMBED_MAX_TOKENS)

    session_options = ort.SessionOptions()
    session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session_options.intra_op_num_threads = min(4, max(1, (os.cpu_count() or 1) - 1))
    session = ort.InferenceSession(
        config.ONNX_MODEL_PATH,
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    return OnnxEmbedder(tokenizer, session)


def _load_model():
    """Load the embedding model, preferring ONNX and falling back to PyTorch."""
    import traceback

    print("[diary-rag] Loading ONNX embedding model...", file=sys.stderr, flush=True)
    try:
        model = _load_onnx_model()
        model.encode(["warm-up"], normalize_embeddings=True, show_progress_bar=False)
        print("[diary-rag] ONNX model ready.", file=sys.stderr, flush=True)
        return model
    except Exception as exc:
        print(
            f"[diary-rag] ONNX load failed ({exc}); falling back to "
            "SentenceTransformer.",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)

    from sentence_transformers import SentenceTransformer

    print("[diary-rag] Loading SentenceTransformer from cache...", file=sys.stderr, flush=True)
    model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)
    model.encode(["warm-up"], normalize_embeddings=True, show_progress_bar=False)
    print("[diary-rag] SentenceTransformer ready.", file=sys.stderr, flush=True)
    return model


def get_model():
    """Return the model, loading it on first access if needed."""
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

# Full text is returned for only the top few distinct parents; the remaining
# matched chunks come back as short slices so payloads stay bounded.
PARENT_FULL_K = 4


@mcp.tool()
def search_diary(query: str, top_k: int = 20) -> dict:
    """Search diary entries by semantic similarity.

    top_k is the number of matched slices returned. Returns
    {"parents": top 4 full parent blocks, "slices": top_k matched chunks with
    short text only (no full parent content)}.

    The exact ``预检`` query is a lightweight readiness probe. It reports
    warm-up state without loading the encoder or querying the index.
    """
    global _warmup_restarts, _warmup_started_at, _warmup_stage, _warmup_generation, _warmup_error
    global _chroma_client, _chroma_collection

    if query.strip() == "预检":
        if _warmup_error:
            return {
                "status": "error",
                "stage": _warmup_stage,
                "message": _warmup_error,
            }
        return {
            "status": "ok" if _prewarm_done.is_set() else "warming",
            "stage": _warmup_stage,
        }

    t_start = time.perf_counter()

    model = get_model()

    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    t_encode = time.perf_counter()

    needs_init = False
    with _chroma_lock:
        if _chroma_client is None:
            needs_init = True

    if needs_init:
        with _chroma_startup_lock():
            with _chroma_lock:
                if _chroma_client is None:
                    new_client, new_collection = _open_chroma()
                    _chroma_client = new_client
                    _chroma_collection = new_collection

    with _chroma_lock:
        collection = _chroma_collection

    fetch_k = max(top_k, PARENT_FULL_K * config.OVERSAMPLE_FACTOR)
    results = collection.query(
        query_embeddings=[query_vec[0].tolist()],
        n_results=fetch_k,
    )
    t_chroma = time.perf_counter()

    if not results["ids"] or not results["ids"][0]:
        return {"parents": [], "slices": []}

    ids = results["ids"][0]
    metadatas = results["metadatas"][0]
    docs = (results.get("documents") or [[]])[0]

    # Parents: dedup chunks by parent_id, keep the top distinct parents.
    seen_parents = set()
    parent_ids = []
    for meta in metadatas:
        pid = meta["parent_id"]
        if pid not in seen_parents and pid not in _returned_ids:
            seen_parents.add(pid)
            parent_ids.append(pid)
            if len(parent_ids) >= PARENT_FULL_K:
                break

    # Slices: all top_k matched chunks themselves — short text only.
    slice_metas = metadatas[:top_k]
    sids = ids[:top_k]
    sdocs = docs[:top_k]
    s_parent_ids = list(dict.fromkeys(m["parent_id"] for m in slice_metas))

    conn = sqlite3.connect(config.DB_PATH)

    parents = []
    if parent_ids:
        placeholders = ",".join(["?" for _ in parent_ids])
        rows = conn.execute(
            "SELECT id, date, title, block_type, char_count, content "
            f"FROM parents WHERE id IN ({placeholders})",
            parent_ids,
        ).fetchall()
        parents = [
            {
                "id": row[0],
                "date": row[1] or "",
                "title": row[2] or "",
                "type": row[3],
                "char_count": row[4],
                "content": row[5],
            }
            for row in rows
        ]

    date_title: dict = {}
    if s_parent_ids:
        placeholders = ",".join(["?" for _ in s_parent_ids])
        for row in conn.execute(
            "SELECT id, date, title, block_type FROM parents "
            f"WHERE id IN ({placeholders})",
            s_parent_ids,
        ).fetchall():
            date_title[row[0]] = (row[1] or "", row[2] or "", row[3])

    slices = [
        {
            "id": sids[i],
            "parent_id": slice_metas[i]["parent_id"],
            "date": date_title.get(slice_metas[i]["parent_id"], ("", "", ""))[0],
            "title": date_title.get(slice_metas[i]["parent_id"], ("", "", ""))[1],
            "type": date_title.get(slice_metas[i]["parent_id"], ("", "", ""))[2],
            "sub_title": slice_metas[i].get("sub_title") or "",
            "content": sdocs[i] if i < len(sdocs) else "",
        }
        for i in range(len(slice_metas))
    ]

    conn.close()
    t_sql = time.perf_counter()

    for pid in parent_ids:
        _returned_ids.add(pid)

    print(
        f"[diary-rag] query done in {t_sql - t_start:.3f}s "
        f"(encode {t_encode - t_start:.3f}s, chroma {t_chroma - t_encode:.3f}s, "
        f"sqlite {t_sql - t_chroma:.3f}s): {query[:40]!r} "
        f"-> {len(parents)} parents / {len(slices)} slices",
        file=sys.stderr,
        flush=True,
    )

    return {"parents": parents, "slices": slices}


@mcp.tool()
def search_diary_batch(queries: list[str], top_k: int = 20) -> list[dict]:
    """Run one retrieval wave containing multiple independent queries.

    This preserves the same per-query retrieval behavior and top_k setting as
    search_diary(), while avoiding multiple MCP round trips.
    """
    clean_queries = [query.strip() for query in queries if query and query.strip()]
    return [
        {"query": query, "hits": search_diary(query, top_k=top_k)}
        for query in clean_queries
    ]


def _prewarm_background(generation: int = 0) -> None:
    """Eager-load the encoder and ChromaDB, then touch the index with a dummy query."""
    global _chroma_client, _chroma_collection, _warmup_stage, _warmup_started_at
    global _warmup_error, _warmup_model_done_at

    t_start = time.time()
    _warmup_started_at = t_start
    _warmup_stage = "model"

    print("[diary-rag] Background pre-warm started (ONNX + ChromaDB)...",
          file=sys.stderr, flush=True)

    t0 = time.time()
    try:
        get_model()
    except Exception as exc:
        _warmup_error = f"Model load failed: {exc}"
        print(f"[diary-rag] Background model load failed: {exc}",
              file=sys.stderr, flush=True)
        return
    t_model = time.time()
    _warmup_model_done_at = t_model
    _warmup_stage = "chromadb"
    print(f"[diary-rag] Model loaded ({t_model - t0:.1f}s).",
          file=sys.stderr, flush=True)

    tc0 = time.time()
    try:
        with _chroma_startup_lock():
            client, collection = _open_chroma()
        with _chroma_lock:
            _chroma_client = client
            _chroma_collection = collection

        print(f"[diary-rag] ChromaDB ready ({time.time() - tc0:.1f}s).",
              file=sys.stderr, flush=True)

        # Force the HNSW index and vector pages into memory before the first
        # real user query; otherwise the first search still pays disk I/O.
        model = get_model()
        warm_vec = model.encode(
            ["预热"],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        collection.query(query_embeddings=[warm_vec[0].tolist()], n_results=1)
        print("[diary-rag] ChromaDB index warmed via dummy query.",
              file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[diary-rag] ChromaDB pre-load failed, will retry on first query: {exc}",
              file=sys.stderr, flush=True)

    if generation != _warmup_generation:
        if _model is not None and _chroma_collection is not None:
            _warmup_stage = "done"
            _prewarm_done.set()
        else:
            print(f"[diary-rag] Stale warmup thread gen={generation} discarding.",
                  file=sys.stderr, flush=True)
        return

    _warmup_stage = "done"
    _prewarm_done.set()
    print(f"[diary-rag] Pre-warm complete ({time.time() - t_start:.1f}s total).",
          file=sys.stderr, flush=True)


if __name__ == "__main__":
    print("[diary-rag] MCP server starting...", file=sys.stderr, flush=True)
    print(f"[diary-rag] ONNX: {config.ONNX_MODEL_PATH}", file=sys.stderr, flush=True)
    print(f"[diary-rag] ChromaDB: {config.CHROMA_DIR}", file=sys.stderr, flush=True)
    print(f"[diary-rag] SQLite: {config.DB_PATH}", file=sys.stderr, flush=True)

    # Import heavy libraries on the main thread before the stdio event loop
    # starts; importing them from a worker thread (tool call or pre-warm)
    # while the event loop is running hangs (observed: import numpy inside a
    # tool call never returns). The pre-warm thread below therefore only uses
    # already-imported modules. The SentenceTransformer fallback is the only
    # other heavy import a thread could trigger, so import it up front when
    # the ONNX files are missing.
    import numpy  # noqa: F401
    import onnxruntime  # noqa: F401
    import tokenizers  # noqa: F401
    import chromadb  # noqa: F401
    if not (os.path.isfile(config.ONNX_MODEL_PATH) and os.path.isfile(config.TOKENIZER_PATH)):
        import sentence_transformers  # noqa: F401

    threading.Thread(
        target=_prewarm_background, kwargs={"generation": 0}, daemon=True
    ).start()
    mcp.run(transport="stdio")
