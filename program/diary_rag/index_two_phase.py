# -*- coding: utf-8 -*-
"""向量导出：
  embed_all  — 一次性把全部 L2 子块编码导出为 data/all_embeddings.npy +
               data/all_meta.json，即 numpy 暴力检索后端的全部数据源。
用法：
  python index_two_phase.py embed_all
"""
import json
import sys

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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "embed_all":
        embed_all()
    else:
        print(__doc__)
