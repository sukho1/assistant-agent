"""MCP Server for diary RAG search. Stdio transport, singleton model.

Fast path: loads the pre-exported BGE ONNX model with onnxruntime and
tokenizers, avoiding the 30-55s PyTorch/sentence-transformers startup.
If the ONNX files or runtime libraries are missing, it falls back to
SentenceTransformer so the server still starts.

Vector search is brute-force numpy over the pre-exported embedding matrix
(all_embeddings.npy + all_meta.json). ChromaDB was dropped from the query
path: its 1.5.9 rust compactor dies on this machine shortly after client
creation, leaving the WAL backlog undrainable and every query failing with
"Failed to apply logs to the metadata segment".

The MCP protocol layer is stdlib-only and answers the handshake immediately;
numpy/onnxruntime/tokenizers are imported only after tools/list has
been answered, because clients freeze their tool set seconds after session
start and a server that is still starting up is dropped for that session.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

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


# ── Singleton model + vector store ──
_model = None
_model_lock = threading.Lock()

_vs = None  # lazily built _VectorStore
_vs_lock = threading.Lock()

_prewarm_done = threading.Event()
_warmup_stage = "init"  # "model" | "vectors" | "done"
_warmup_started_at: float | None = None

WARMUP_TIMEOUT_S = 75
_warmup_restarts = 0
MAX_WARMUP_RESTARTS = 2

_warmup_error: str | None = None
_warmup_model_done_at: float | None = None
_warmup_generation: int = 0


class _VectorStore:
    """Brute-force cosine search over the pre-exported embedding matrix.

    Replaces ChromaDB, whose 1.5.9 rust compactor dies shortly after client
    creation on this machine; queries then fail forever with "Failed to apply
    logs to the metadata segment" and the WAL backlog can never drain. The
    exported matrix is complete, and a 33k x 512 matmul is milliseconds.
    """

    def __init__(self):
        import numpy as np

        embeddings = np.load(config.EMBEDDINGS_PATH)
        with open(config.META_PATH, encoding="utf-8") as fh:
            meta = json.load(fh)
        if embeddings.shape[0] != len(meta):
            raise RuntimeError(
                f"embedding/meta mismatch: {embeddings.shape[0]} rows vs "
                f"{len(meta)} meta entries")
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms < 1e-12] = 1.0
        self._np = np
        self._matrix = np.ascontiguousarray(embeddings / norms, dtype=np.float32)
        self._meta = meta
        self.size = len(meta)

    def search(self, query_vec, fetch_k):
        """Return (ids, metadatas, documents) for the top fetch_k chunks."""
        np = self._np
        sims = self._matrix @ np.asarray(query_vec, dtype=np.float32)
        order = np.argsort(-sims)[:fetch_k]
        meta_keys = ("id", "parent_id", "seq", "sub_title", "char_count")
        ids, metadatas, documents = [], [], []
        for i in order:
            m = self._meta[int(i)]
            ids.append(m["id"])
            metadatas.append({k: m[k] for k in meta_keys if k in m})
            documents.append(m.get("content", ""))
        return ids, metadatas, documents


def _get_vector_store() -> "_VectorStore":
    global _vs
    if _vs is None:
        with _vs_lock:
            if _vs is None:
                _vs = _VectorStore()
    return _vs


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


# ── Tools ──
# Full text is returned for only the top few distinct parents; the remaining
# matched chunks come back as short slices so payloads stay bounded.
PARENT_FULL_K = 4


def search_diary(query: str, top_k: int = 20) -> dict:
    """Search diary entries by semantic similarity.

    top_k is the number of matched slices returned. Returns
    {"parents": top 4 full parent blocks, "slices": top_k matched chunks with
    short text only (no full parent content)}.

    The exact ``预检`` query is a lightweight readiness probe. It reports
    warm-up state without loading the encoder or querying the index.
    """
    global _warmup_restarts, _warmup_started_at, _warmup_stage, _warmup_generation, _warmup_error

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

    _ensure_imports()

    model = get_model()

    query_vec = model.encode(
        [query],
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    t_encode = time.perf_counter()

    vector_store = _get_vector_store()

    fetch_k = max(top_k, PARENT_FULL_K * config.OVERSAMPLE_FACTOR)
    ids, metadatas, docs = vector_store.search(query_vec[0], fetch_k)
    t_search = time.perf_counter()

    if not ids:
        return {"parents": [], "slices": []}

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
        f"(encode {t_encode - t_start:.3f}s, search {t_search - t_encode:.3f}s, "
        f"sqlite {t_sql - t_search:.3f}s): {query[:40]!r} "
        f"-> {len(parents)} parents / {len(slices)} slices",
        file=sys.stderr,
        flush=True,
    )

    return {"parents": parents, "slices": slices}


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
    """Eager-load the encoder and vector store, then touch the index with a dummy query."""
    global _warmup_stage, _warmup_started_at
    global _warmup_error, _warmup_model_done_at

    t_start = time.time()
    _warmup_started_at = t_start
    _warmup_stage = "model"

    print("[diary-rag] Background pre-warm started (ONNX + vector store)...",
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
    _warmup_stage = "vectors"
    print(f"[diary-rag] Model loaded ({t_model - t0:.1f}s).",
          file=sys.stderr, flush=True)

    tv0 = time.time()
    try:
        vector_store = _get_vector_store()
        print(f"[diary-rag] Vector store ready ({time.time() - tv0:.1f}s, "
              f"{vector_store.size} blocks).", file=sys.stderr, flush=True)

        # Force the vector matrix pages into memory before the first real
        # user query; otherwise the first search still pays disk I/O.
        model = get_model()
        warm_vec = model.encode(
            ["预热"],
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        vector_store.search(warm_vec[0], 1)
        print("[diary-rag] Vector index warmed via dummy search.",
              file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[diary-rag] Vector store pre-load failed, will retry on first query: {exc}",
              file=sys.stderr, flush=True)

    if generation != _warmup_generation:
        if _model is not None and _vs is not None:
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


# ── Runtime loading (deferred until after the handshake) ──
_import_lock = threading.Lock()
_imports_ready = False
_prewarm_started = False


def _ensure_imports() -> None:
    """Import the encoder/vector-store stack once, in the calling thread.

    Never runs at module import and never in a worker thread: importing these
    from a thread while the serving loop is active was observed to hang (import
    numpy inside a tool call never returned), so callers stay on the thread that
    owns the request.
    """
    global _imports_ready
    if _imports_ready:
        return
    with _import_lock:
        if _imports_ready:
            return
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
        if not (os.path.isfile(config.ONNX_MODEL_PATH) and os.path.isfile(config.TOKENIZER_PATH)):
            import sentence_transformers  # noqa: F401
        _imports_ready = True


def _start_prewarm() -> None:
    """Load the encoder and vector store in the background; safe to call repeatedly."""
    global _prewarm_started
    if _prewarm_started:
        return
    _ensure_imports()
    with _import_lock:
        if _prewarm_started:
            return
        _prewarm_started = True
    threading.Thread(
        target=_prewarm_background, kwargs={"generation": 0}, daemon=True
    ).start()


# ── MCP protocol layer (stdlib only) ──
SERVER_NAME = "diary-rag"
SERVER_VERSION = "2.0.0"
LATEST_PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    LATEST_PROTOCOL_VERSION,
)


def _tool_definitions() -> list[dict]:
    """Tool schemas as advertised to clients.

    The input/output schemas mirror the previously generated FastMCP schemas, so
    clients see the same tools as before; descriptions come from the docstrings.
    """
    return [
        {
            "name": "search_diary",
            "description": search_diary.__doc__,
            "inputSchema": {
                "properties": {
                    "query": {"title": "Query", "type": "string"},
                    "top_k": {"default": 20, "title": "Top K", "type": "integer"},
                },
                "required": ["query"],
                "title": "search_diaryArguments",
                "type": "object",
            },
        },
        {
            "name": "search_diary_batch",
            "description": search_diary_batch.__doc__,
            "inputSchema": {
                "properties": {
                    "queries": {
                        "items": {"type": "string"},
                        "title": "Queries",
                        "type": "array",
                    },
                    "top_k": {"default": 20, "title": "Top K", "type": "integer"},
                },
                "required": ["queries"],
                "title": "search_diary_batchArguments",
                "type": "object",
            },
            "outputSchema": {
                "properties": {
                    "result": {
                        "items": {"additionalProperties": True, "type": "object"},
                        "title": "Result",
                        "type": "array",
                    }
                },
                "required": ["result"],
                "title": "search_diary_batchOutput",
                "type": "object",
            },
        },
    ]


def _json_text(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _top_k_argument(arguments: dict) -> int:
    raw = arguments.get("top_k", 20)
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError("top_k must be an integer")


def _run_search_diary(arguments) -> dict:
    if not isinstance(arguments, dict):
        return _tool_error("Error executing tool search_diary: arguments must be an object")
    query = arguments.get("query")
    if not isinstance(query, str):
        return _tool_error("Error executing tool search_diary: query is required and must be a string")
    try:
        top_k = _top_k_argument(arguments)
    except ValueError as exc:
        return _tool_error(f"Error executing tool search_diary: {exc}")
    try:
        result = search_diary(query, top_k=top_k)
    except Exception as exc:
        return _tool_error(f"Error executing tool search_diary: {exc}")
    return {"content": [{"type": "text", "text": _json_text(result)}], "isError": False}


def _run_search_diary_batch(arguments) -> dict:
    if not isinstance(arguments, dict):
        return _tool_error("Error executing tool search_diary_batch: arguments must be an object")
    queries = arguments.get("queries")
    if not isinstance(queries, list) or not all(isinstance(q, str) for q in queries):
        return _tool_error(
            "Error executing tool search_diary_batch: queries is required and must be a list of strings"
        )
    try:
        top_k = _top_k_argument(arguments)
    except ValueError as exc:
        return _tool_error(f"Error executing tool search_diary_batch: {exc}")
    try:
        results = search_diary_batch(queries, top_k=top_k)
    except Exception as exc:
        return _tool_error(f"Error executing tool search_diary_batch: {exc}")
    return {
        "content": [{"type": "text", "text": _json_text(item)} for item in results],
        "structuredContent": {"result": results},
        "isError": False,
    }


def _handle_message(message: dict) -> dict | None:
    """Build the JSON-RPC response for one request; None for notifications."""
    request_id = message.get("id")
    if request_id is None:
        return None
    method = message.get("method")
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = (
            requested
            if requested in SUPPORTED_PROTOCOL_VERSIONS
            else LATEST_PROTOCOL_VERSION
        )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": _tool_definitions()}}
    if method == "tools/call":
        name = params.get("name")
        if name == "search_diary":
            result = _run_search_diary(params.get("arguments"))
        elif name == "search_diary_batch":
            result = _run_search_diary_batch(params.get("arguments"))
        else:
            result = _tool_error(f"Unknown tool: {name}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _serve_stdio() -> None:
    """Serve MCP over stdio with nothing but the standard library.

    Reading with readline() (not iteration) avoids the read-ahead buffering that
    would delay requests on a pipe. The encoder/vector store is loaded after the
    tool list is on the wire, so the handshake — which is what the client's tool
    snapshot depends on — never waits for it.
    """
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    handshake_answered = False
    while True:
        raw = stdin.readline()
        if not raw:
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if not isinstance(message, dict):
            continue

        # The tools are already registered on the client side; the first request
        # that follows pays the runtime load (and warms it for later calls).
        if handshake_answered:
            _start_prewarm()

        response = _handle_message(message)
        if response is not None:
            stdout.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
            stdout.flush()
        if message.get("method") == "tools/list":
            handshake_answered = True


if __name__ == "__main__":
    print("[diary-rag] MCP server starting...", file=sys.stderr, flush=True)
    print(f"[diary-rag] ONNX: {config.ONNX_MODEL_PATH}", file=sys.stderr, flush=True)
    print(f"[diary-rag] Vectors: {config.EMBEDDINGS_PATH}", file=sys.stderr, flush=True)
    print(f"[diary-rag] SQLite: {config.DB_PATH}", file=sys.stderr, flush=True)
    _serve_stdio()
