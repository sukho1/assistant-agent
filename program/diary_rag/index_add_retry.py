# -*- coding: utf-8 -*-
"""带重试的分批灌库：替代 index.py 的裸 add。

chroma 1.5.9 rust compaction 在本机偶发 "Failed to apply logs to the
metadata segment"（非确定性，同一批次重试即可通过），故每批 add 失败后
退避重试。其余逻辑与 index.py 一致：全量重建 diary_rag collection。
"""
import time
import sys

import chromadb

import config


def main():
    print("Loading embedding model...", flush=True)
    try:
        from server import _load_onnx_model
        model = _load_onnx_model()
    except Exception:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)
    print("  model ready", flush=True)
    model.encode(["预热"], normalize_embeddings=True, show_progress_bar=False)

    from index import load_child_chunks
    chunks = load_child_chunks()
    total = len(chunks)
    print(f"{total} chunks to index", flush=True)

    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    existing = collection.count()
    if existing:
        print(f"  清空旧数据 {existing} 条...", flush=True)
        got = collection.get(include=[])
        old_ids = got["ids"]
        for i in range(0, len(old_ids), 500):
            collection.delete(ids=old_ids[i:i + 500])
        print(f"  清空完成，现有 {collection.count()} 条", flush=True)

    batch_size = config.EMBED_BATCH_SIZE
    added = 0
    t0 = time.time()
    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        ids = [f"{c['id']}" for c in batch]
        texts = [c["content"] for c in batch]
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        metadatas = [{
            "id": c.get("id", ""),
            "parent_id": c.get("parent_id", ""),
            "seq": c.get("seq", 0),
            "sub_title": c.get("sub_title", "") or "",
            "char_count": c["char_count"],
        } for c in batch]

        for attempt in range(1, 7):
            try:
                collection.add(ids=ids, embeddings=embeddings.tolist(),
                               documents=texts, metadatas=metadatas)
                break
            except Exception as e:
                wait = min(2 * attempt, 10)
                print(f"  [retry {attempt}] batch@{i}: {str(e)[:90]} — sleep {wait}s", flush=True)
                time.sleep(wait)
        else:
            print(f"!! 批次 @{i} 六次重试后仍失败，跳过（记入日志）", flush=True)
            continue
        added += len(ids)
        done = i + len(batch)
        if done % 320 < batch_size or done == total:
            rate = done / max(time.time() - t0, 1)
            eta = (total - done) / max(rate, 1e-9)
            print(f"  {done}/{total} ({done*100//total}%)  {rate:.0f}/s  ETA {eta/60:.1f}min", flush=True)

    print(f"Done. added={added}/{total}, collection.count={collection.count()}", flush=True)


if __name__ == "__main__":
    main()
