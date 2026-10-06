"""Tests for diary_rag.server — RED phase."""
import os
import sys
import tempfile
import sqlite3
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestServerSearch:

    def test_server_module_imports(self):
        """server module imports without error."""
        from server import search_diary, search_diary_batch, get_model, _tool_definitions
        assert callable(search_diary)
        assert callable(search_diary_batch)
        assert callable(get_model)
        assert search_diary_batch([], top_k=20) == []
        tools = {t["name"]: t for t in _tool_definitions()}
        assert set(tools) == {"search_diary", "search_diary_batch"}
        assert tools["search_diary"]["inputSchema"]["required"] == ["query"]
        assert tools["search_diary_batch"]["inputSchema"]["required"] == ["queries"]

    def test_precheck_is_lightweight(self):
        """The readiness probe reports state without running semantic search."""
        import server

        original_done = server._prewarm_done.is_set()
        original_stage = server._warmup_stage
        original_error = server._warmup_error
        original_get_model = server.get_model

        try:
            server._warmup_stage = "done"
            server._warmup_error = None
            server._prewarm_done.set()

            def fail_if_called():
                raise AssertionError("precheck must not load the embedding model")

            server.get_model = fail_if_called
            result = server.search_diary("预检", top_k=1)

            assert result == {"status": "ok", "stage": "done"}
        finally:
            server.get_model = original_get_model
            server._warmup_stage = original_stage
            server._warmup_error = original_error
            if original_done:
                server._prewarm_done.set()
            else:
                server._prewarm_done.clear()

    def test_search_with_data(self):
        """search returns parent blocks for a matching query."""
        from server import search_diary, _prewarm_done
        import config

        original_db = config.DB_PATH
        original_emb = config.EMBEDDINGS_PATH
        original_meta = config.META_PATH
        tmp_dir = tempfile.mkdtemp()

        try:
            # Create temp SQLite with a parent
            db_path = os.path.join(tmp_dir, "test.db")
            config.DB_PATH = db_path
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parents (
                    id TEXT PRIMARY KEY, date TEXT, title TEXT, block_type TEXT,
                    char_count INTEGER, file_src TEXT, content TEXT,
                    confidence REAL, para_start INTEGER, para_end INTEGER
                )
            """)
            conn.execute(
                "INSERT INTO parents VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("2026-01-05_diary_0", "2026.1.5", "测试日记", "diary",
                 100, "test.docx", "今天天气很好，出门散步。", 0.95, 0, 2)
            )
            conn.commit()
            conn.close()

            # Build a temp vector store with one child chunk
            try:
                from server import _load_onnx_model
                model = _load_onnx_model()
            except Exception:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer(config.EMBED_MODEL_NAME)
            text = "今天天气很好，出门散步。"
            embedding = model.encode(
                [text],
                normalize_embeddings=True,
                show_progress_bar=False
            )

            import numpy as np
            emb_path = os.path.join(tmp_dir, "all_embeddings.npy")
            meta_path = os.path.join(tmp_dir, "all_meta.json")
            np.save(emb_path, embedding.astype(np.float32))
            meta = [{"id": "2026-01-05_diary_0_ch0", "parent_id": "2026-01-05_diary_0",
                     "seq": 0, "sub_title": "", "char_count": len(text), "content": text}]
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh, ensure_ascii=False)
            config.EMBEDDINGS_PATH = emb_path
            config.META_PATH = meta_path

            # Initialize server globals so search_diary() uses the temp store
            import server
            server._model = model
            server._vs = server._VectorStore()
            server._prewarm_done.set()

            # Test search
            results = search_diary("天气很好", top_k=1)
            assert len(results["parents"]) > 0, f"Expected results, got {results}"
            assert results["parents"][0]["title"] == "测试日记"
            assert "天气很好" in results["parents"][0]["content"]
            assert len(results["slices"]) == 1

            # Full parents are session-deduped; matching slices remain available.
            results2 = search_diary("天气很好", top_k=1)
            assert results2["parents"] == []
            assert len(results2["slices"]) == 1

        finally:
            config.DB_PATH = original_db
            config.EMBEDDINGS_PATH = original_emb
            config.META_PATH = original_meta
            import server
            server._vs = None
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            # Reset session dedup state
            try:
                from server import _returned_ids
                _returned_ids.clear()
            except Exception:
                pass


if __name__ == '__main__':
    suite = TestServerSearch()
    passed = 0
    failed = 0
    for name in dir(suite):
        if name.startswith('test_'):
            fn = getattr(suite, name)
            try:
                fn()
                print(f"  PASS {name}")
                passed += 1
            except ModuleNotFoundError as e:
                print(f"  FAIL {name}: module not found - {e}")
                failed += 1
            except Exception as e:
                import traceback
                print(f"  FAIL {name}: {e}")
                traceback.print_exc()
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed > 0:
        print("RED")
