# -*- coding: utf-8 -*-
"""compactor 压力探针：单进程连灌 256 条 768 维合成数据，逐批记录成败。
用于判定 compactor 死点是否与进程派生环境相关（ZCode 内 vs 计划任务）。"""
import json
import random

import chromadb

c = chromadb.PersistentClient(path="data/chroma")
col = c.get_or_create_collection(name="probe_stress", metadata={"hnsw:space": "cosine"})
vecs = [[random.random() for _ in range(768)] for _ in range(32)]
for b in range(8):
    ids = [f"s{b}_{i}" for i in range(32)]
    metas = [{"id": f"s{b}_{i}", "parent_id": f"p{b}", "seq": i, "sub_title": "t", "char_count": 10} for i in range(32)]
    try:
        col.add(ids=ids, embeddings=vecs, documents=["d"] * 32, metadatas=metas)
        print(f"batch {b} (@{b*32}-{b*32+31}): OK", flush=True)
    except Exception as e:
        print(f"batch {b} (@{b*32}-{b*32+31}): FAIL {str(e)[:60]}", flush=True)
try:
    print("final count:", col.count(), flush=True)
except Exception as e:
    print("final count FAIL:", str(e)[:60], flush=True)
c.delete_collection("probe_stress")
print("cleaned", flush=True)
