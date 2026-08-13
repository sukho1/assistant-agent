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
        from server import mcp, search_diary, get_model
        assert mcp is not None
        assert callable(search_diary)

    def test_search_with_data(self):
        """search returns parent blocks for a matching query."""
        from server import search_diary, _model, _chroma_client, _chroma_collection, _prewarm_done
        import config
        import chromadb
        from sentence_transformers import SentenceTransformer

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
            assert len(results) > 0, f"Expected results, got empty list"
            assert results[0]["title"] == "测试日记"
            assert "天气很好" in results[0]["content"]

            # Test session dedup: second call should return empty (already returned)
            results2 = search_diary("天气很好", top_k=1)
            assert len(results2) == 0, f"Expected empty (session dedup), got {len(results2)}"

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
