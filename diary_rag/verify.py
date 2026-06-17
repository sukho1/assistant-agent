"""Verification: check diary processing is complete and MCP search works."""

import sqlite3
import glob
import os
import sys

import chromadb
from sentence_transformers import SentenceTransformer
import config


def check_l1():
    """Check parent blocks exist in SQLite."""
    if not os.path.exists(config.DB_PATH):
        print("  FAIL: diary.db not found — L1 segmentation not run")
        return False

    conn = sqlite3.connect(config.DB_PATH)
    try:
        row = conn.execute("SELECT id FROM parents LIMIT 1").fetchone()
        if row:
            count = conn.execute("SELECT COUNT(*) FROM parents").fetchone()[0]
            print(f"  PASS: L1 — {count} parent blocks in database")
            return True
        else:
            print("  FAIL: L1 — 0 parent blocks (diary/ empty?)")
            return False
    finally:
        conn.close()


def check_l2():
    """Check child chunk cache files exist."""
    files = glob.glob(os.path.join(config.CACHE_DIR, "*.l2.json"))
    if not files:
        print("  FAIL: L2 — no .l2.json cache files found")
        return False

    total = 0
    for f in files:
        total += len(__import__('json').load(open(f, 'r', encoding='utf-8')))
    print(f"  PASS: L2 — {len(files)} cache files, {total} child chunks")
    return True


def check_index():
    """Check ChromaDB has embeddings."""
    if not os.path.exists(config.CHROMA_DIR):
        print("  FAIL: Index — ChromaDB directory not found")
        return False

    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    try:
        collection = client.get_collection(config.COLLECTION_NAME)
        count = collection.count()
        if count > 0:
            print(f"  PASS: Index — {count} vectors in ChromaDB")
            return True
        else:
            print("  FAIL: Index — collection exists but empty")
            return False
    except Exception:
        print("  FAIL: Index — collection not found, index.py not run")
        return False


def check_search():
    """Test an actual MCP search query."""
    try:
        from server import search
        results = search("日记", top_k=2)
        if results is not None and len(results) >= 0:
            print(f"  PASS: MCP search — returned {len(results)} results for '日记'")
            if results:
                r = results[0]
                print(f"         top result: {r.get('date','?')} | {r.get('title','?')}")
            return True
        else:
            print("  FAIL: MCP search — returned None")
            return False
    except Exception as e:
        print(f"  FAIL: MCP search — {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("[diary_rag] Verifying...\n")

    ok = all([
        check_l1(),
        check_l2(),
        check_index(),
        check_search(),
    ])

    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED — check diary/ files and re-run segment_l1/l2/index'}")
    sys.exit(0 if ok else 1)
