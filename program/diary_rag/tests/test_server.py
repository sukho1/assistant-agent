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
        from server import mcp, search_diary, search_diary_batch, get_model
        assert mcp is not None
        assert callable(search_diary)
        assert callable(search_diary_batch)
        assert search_diary_batch([], top_k=20) == []

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
        from server import search_diary, _model, _chroma_client, _chroma_collection, _prewarm_done
        import config
        import chromadb

        # Setup: temp ChromaDB + SQLite with test data
        original_chroma = config.CHROMA_DIR
        original_db = config.DB_PATH
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

            # Create temp ChromaDB with a child chunk
            chroma_dir = os.path.join(tmp_dir, "chroma")
            config.CHROMA_DIR = chroma_dir
            client = chromadb.PersistentClient(path=chroma_dir)
            collection = client.create_collection(
                name=config.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )

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
            collection.add(
                ids=["2026-01-05_diary_0_ch0"],
                embeddings=embedding.tolist(),
                documents=[text],
                metadatas=[{"parent_id": "2026-01-05_diary_0", "sub_title": "", "char_count": len(text)}]
            )

            # Initialize server globals so search_diary() doesn't block on warming_up
            import server
            server._model = model
            server._chroma_client = client
            server._chroma_collection = collection
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
            config.CHROMA_DIR = original_chroma
            config.DB_PATH = original_db
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)
            # Reset session dedup state
            try:
                from server import _returned_ids
                _returned_ids.clear()
            except:
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
