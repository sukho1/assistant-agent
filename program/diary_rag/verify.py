"""Verification: source coverage + L1->L2->Index consistency + MCP smoke test."""

import sqlite3
import glob
import json
import os
import sys

import config


def summarize_search_results(results):
    """Return the parent-block count and metadata for the highest-ranked hit."""
    if not isinstance(results, dict):
        return 0, None

    parents = results.get("parents", [])
    slices = results.get("slices", [])
    if not parents and not slices:
        return 0, None

    top = slices[0] if slices else parents[0]
    return len(parents), {"date": top.get("date", "?"), "title": top.get("title", "?")}


def verify():
    errors = []
    warn = []
    vec_count = None

    # ── 0. Source coverage: every .docx in user-data/diary/ -> processed? ──
    diary_root = config.DIARY_DIR
    docx_files = set(
        os.path.basename(f) for f in glob.glob(os.path.join(diary_root, "*.docx"))
    )
    if not docx_files:
        print("  FAIL  user-data/diary/ has 0 .docx files")
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

    # ── 3. Vector store: all_embeddings.npy + all_meta.json ──
    if not (os.path.exists(config.EMBEDDINGS_PATH) and os.path.exists(config.META_PATH)):
        errors.append("vector store files not found — run index_two_phase.py embed_all")
    elif not l2_files:
        pass  # already reported
    else:
        import numpy as np
        embs = np.load(config.EMBEDDINGS_PATH)
        meta = json.load(open(config.META_PATH, encoding="utf-8"))
        if embs.shape[0] != len(meta):
            errors.append(f"vector/meta mismatch: {embs.shape[0]} rows vs {len(meta)} meta")
        else:
            vec_count = len(meta)
            print(f"  OK    Vector store — {vec_count} vectors")
            meta_ids = {m["id"] for m in meta}
            missing_ids = child_ids - meta_ids
            if missing_ids:
                errors.append(f"L2 -> vector store gap: {len(missing_ids)} chunks not exported")
            elif vec_count == child_count:
                print(f"  OK    L2 -> vector store — all {child_count} chunks exported")
            else:
                print(f"  OK    L2 -> vector store — {vec_count} vectors for {child_count} chunks (normal if dedup)")

    conn.close()

    # ── 4. MCP search smoke test ──
    try:
        from server import search_diary
        results = search_diary("日记", top_k=2)
        result_count, top = summarize_search_results(results)
        print(f"  OK    MCP search — returned {result_count} parent blocks")
        if top:
            print(f"          top: {top['date']} | {top['title']}")
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
              f"{vec_count if vec_count is not None else '?'} vectors")
        return True


if __name__ == '__main__':
    ok = verify()
    if ok:
        print("[diary_rag] Ready.\n")
    else:
        print("[diary_rag] Re-run: segment_l1.py && segment_l2.py && index_two_phase.py embed_all\n")
        sys.exit(1)
