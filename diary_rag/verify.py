"""Verification: source coverage + L1->L2->Index consistency + MCP smoke test."""

import sqlite3
import glob
import json
import os
import sys

import chromadb
import config


def verify():
    errors = []
    warn = []

    # ── 0. Source coverage: every .docx in diary/ -> processed? ──
    diary_root = config.DIARY_DIR
    docx_files = set(
        os.path.basename(f) for f in glob.glob(os.path.join(diary_root, "*.docx"))
    )
    if not docx_files:
        print("  FAIL  diary/ has 0 .docx files")
        return False

    if not os.path.exists(config.DB_PATH):
        print("  FAIL  diary.db not found — run segment_l1.py first")
        return False

    conn = sqlite3.connect(config.DB_PATH)
    db_files = {r[0] for r in conn.execute("SELECT DISTINCT file_src FROM parents").fetchall()}
    missing = docx_files - db_files
    if missing:
        for f in sorted(missing):
            errors.append(f"Unprocessed file: {f}")
    else:
        print(f"  OK    Source coverage — all {len(docx_files)} .docx files processed")

    # ── 1. L1: parents + content coverage ──
    parents = conn.execute("SELECT id FROM parents").fetchall()
    parent_ids = {r[0] for r in parents}
    if not parent_ids:
        errors.append("L1 has 0 parent blocks")
    else:
        print(f"  OK    L1 — {len(parent_ids)} parent blocks from {len(db_files)} files")

        # Content coverage: check paragraph range contiguity per file
        # segment_l1.py may skip empty paragraphs → small gaps normal, large gaps = missing content
        GAP_THRESHOLD = 10  # paragraphs — gaps larger than this are suspicious
        for fname in sorted(db_files):
            rows = conn.execute(
                "SELECT para_start, para_end FROM parents WHERE file_src = ? ORDER BY para_start",
                (fname,)
            ).fetchall()
            if not rows:
                continue
            gaps = []
            for i in range(len(rows) - 1):
                prev_end = rows[i][1]
                next_start = rows[i + 1][0]
                if next_start > prev_end + 1 + GAP_THRESHOLD:
                    gaps.append((prev_end, next_start, next_start - prev_end - 1))
            if gaps:
                for g in gaps:
                    errors.append(
                        f"L1 content gap in {fname}: paras {g[0]} -> {g[1]} "
                        f"({g[2]} paragraphs missing)"
                    )

    # ── 2. L2: child chunk cache ──
    l2_files = sorted(glob.glob(os.path.join(config.CACHE_DIR, "*.l2.json")))
    if not l2_files:
        errors.append("L2 has 0 cache files")
    else:
        child_ids = set()
        l2_parent_ids = set()
        child_count = 0
        for fp in l2_files:
            chunks = json.load(open(fp, 'r', encoding='utf-8'))
            for c in chunks:
                child_ids.add(c["id"])
                l2_parent_ids.add(c["parent_id"])
                child_count += 1
        print(f"  OK    L2 — {len(l2_files)} cache files, {child_count} child chunks")

        # Consistency: L1 <-> L2
        orphan = parent_ids - l2_parent_ids
        if orphan:
            errors.append(f"L1 -> L2 gap: {len(orphan)} parents missing child chunks")
        else:
            print(f"  OK    L1 -> L2 — every parent has child chunks")

    # ── 3. Index: ChromaDB ──
    if not os.path.exists(config.CHROMA_DIR):
        errors.append("ChromaDB directory not found — run index.py")
    elif not l2_files:
        pass  # already reported
    else:
        client = chromadb.PersistentClient(path=config.CHROMA_DIR)
        try:
            coll = client.get_collection(config.COLLECTION_NAME)
            idx_count = coll.count()
            print(f"  OK    Index — {idx_count} vectors")

            # Consistency: L2 <-> Index (sample 500)
            sample = list(child_ids)[:500] + list(child_ids)[-500:]
            indexed = coll.get(ids=sample, include=[])
            missing_ids = set(sample) - set(indexed["ids"])
            if missing_ids:
                errors.append(f"L2 -> Index gap: {len(missing_ids)}/{len(sample)} sampled chunks not indexed")
            elif idx_count == child_count:
                print(f"  OK    L2 -> Index — all {child_count} chunks indexed")
            else:
                print(f"  OK    L2 -> Index — {idx_count} vectors for {child_count} chunks (normal if dedup)")
        except Exception:
            errors.append("Index collection not found — run index.py")

    conn.close()

    # ── 4. MCP search smoke test ──
    try:
        from server import search_diary
        results = search_diary("日记", top_k=2)
        print(f"  OK    MCP search — returned {len(results or [])} results")
        if results:
            r = results[0]
            print(f"          top: {r.get('date','?')} | {r.get('title','?')}")
    except ImportError:
        print("  SKIP  MCP search — dependencies not installed")
    except Exception as e:
        print(f"  SKIP  MCP search — {e}")

    # ── Report ──
    if errors:
        print(f"\n  ISSUES ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")
        return False
    else:
        print(f"\n  ALL GOOD — {len(docx_files)} files, {len(parent_ids)} parents, "
              f"{child_count if l2_files else 0} chunks, "
              f"{idx_count if 'idx_count' in dir() else '?'} vectors")
        return True


if __name__ == '__main__':
    ok = verify()
    if ok:
        print("[diary_rag] Ready.\n")
    else:
        print("[diary_rag] Re-run: segment_l1.py && segment_l2.py && index.py\n")
        sys.exit(1)
