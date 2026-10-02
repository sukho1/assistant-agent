# -*- coding: utf-8 -*-
"""两阶段索引：
  embed_all  — 一次性把全部子块编码成 .npy（不碰 chroma）
  adder      — 全新进程里把 [start,end) 区段灌入 chroma（带重试）
  holes      — 报告 collection 里缺失的 id
用法：
  python index_two_phase.py embed_all
  python index_two_phase.py adder <start> <end>
  python index_two_phase.py holes
"""
import json
import sys
import time

import numpy as np

import config


def _chunks():
    from index import load_child_chunks
    return load_child_chunks()


def embed_all():
    chunks = _chunks()
    try:
        from server import _load_onnx_model
        model = _load_onnx_model()
    except Exception:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)
    texts = [c["content"] for c in chunks]
    print(f"encoding {len(texts)} chunks...", flush=True)
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=True)
    np.save("data/all_embeddings.npy", embs)
    meta = [{"id": c["id"], "parent_id": c.get("parent_id", ""), "seq": c.get("seq", 0),
             "sub_title": c.get("sub_title", "") or "", "char_count": c["char_count"],
             "content": c["content"]} for c in chunks]
    with open("data/all_meta.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    print("saved: data/all_embeddings.npy + data/all_meta.json", flush=True)


def adder(start: int, end: int):
    import chromadb
    embs = np.load("data/all_embeddings.npy")
    meta = json.load(open("data/all_meta.json", encoding="utf-8"))
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    col = client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    # 已存在的 id 跳过（幂等，支持补洞）
    have = set()
    n = col.count()
    if n:
        got = col.get(include=[])
        have = set(got["ids"])
    batch = 32
    i = start
    t0 = time.time()
    while i < end:
        j = min(i + batch, end)
        ids = [meta[k]["id"] for k in range(i, j) if meta[k]["id"] not in have]
        if not ids:
            i = j
            continue
        vecs = embs[i:j].tolist()
        docs = [meta[k]["content"] for k in range(i, j)]
        metas = [{k2: meta[k][k2] for k2 in ("id", "parent_id", "seq", "sub_title", "char_count")}
                 for k in range(i, j)]
        for attempt in range(1, 7):
            try:
                col.add(ids=ids, embeddings=vecs, documents=docs, metadatas=metas)
                break
            except Exception as e:
                wait = min(2 * attempt, 10)
                print(f"  [retry {attempt}] @{i}: {str(e)[:80]} — sleep {wait}", flush=True)
                time.sleep(wait)
        else:
            print(f"!! SKIP @{i}", flush=True)
        i = j
        if (i - start) % 640 < batch:
            rate = (i - start) / max(time.time() - t0, 1)
            print(f"  {i}/{end}  {rate:.0f}/s", flush=True)
    print(f"adder [{start},{end}) done, count={col.count()}", flush=True)


def holes():
    import chromadb
    embs = np.load("data/all_embeddings.npy")
    meta = json.load(open("data/all_meta.json", encoding="utf-8"))
    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    col = client.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    have = set(col.get(include=[])["ids"])
    missing = [k for k, m in enumerate(meta) if m["id"] not in have]
    print(f"缺失 {len(missing)} / {len(meta)}", flush=True)
    # 分小批补
    b = 16
    for s in range(0, len(missing), b):
        ks = missing[s:s + b]
        for attempt in range(1, 7):
            try:
                col.add(ids=[meta[k]["id"] for k in ks],
                        embeddings=embs[ks].tolist(),
                        documents=[meta[k]["content"] for k in ks],
                        metadatas=[{k2: meta[k][k2] for k2 in ("id", "parent_id", "seq", "sub_title", "char_count")} for k in ks])
                break
            except Exception as e:
                print(f"  [retry {attempt}] @{s}: {str(e)[:80]}", flush=True)
                time.sleep(min(2 * attempt, 10))
        else:
            print(f"!! 段 @{s} 放弃", flush=True)
    have2 = set(col.get(include=[])["ids"])
    still = [m["id"] for m in meta if m["id"] not in have2]
    print(f"补洞后缺失: {len(still)}", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "embed_all":
        embed_all()
    elif cmd == "adder":
        adder(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "holes":
        holes()
    else:
        print(__doc__)
