# -*- coding: utf-8 -*-
"""清空-写入循环灌库（绕过 chroma 1.5.9 rust compactor 的机器级故障）。

故障：compactor 线程在 client 创建后 ~6-10 秒死亡（合成/真实数据无关，
计划任务/沙箱内均复现），之后所有 add/count 失败，队列永久卡死。

策略（循环）：
  清空 embeddings_queue（sqlite 直删）→ 重建 client → 从未写入的 id 里
  逐批 add，直到第一次失败 → 下一轮。
  失败批中"已入队未压缩"的数据会随队列清空而丢失，由末尾的对账按
  id 差集补齐，直到 collection 实际拥有全部 32781 个 id。
"""
import json
import sqlite3
import sys
import time

import numpy as np
import chromadb
from chromadb.api.shared_system_client import SharedSystemClient

import config

CHROMA_SQLITE = config.CHROMA_DIR.rstrip("\\/") + "/chroma.sqlite3"
BATCH = 32
META_KEYS = ("id", "parent_id", "seq", "sub_title", "char_count")


def purge_queue():
    for attempt in range(6):
        try:
            conn = sqlite3.connect(CHROMA_SQLITE, timeout=10)
            conn.execute("DELETE FROM embeddings_queue")
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"  [purge {attempt}] {str(e)[:60]}", flush=True)
            time.sleep(2)
    return False


def fresh_col():
    try:
        SharedSystemClient._identifier_to_system.clear()
    except Exception:
        pass
    c = chromadb.PersistentClient(path=config.CHROMA_DIR)
    return c.get_or_create_collection(
        name=config.COLLECTION_NAME, metadata={"hnsw:space": "cosine"})


def have_ids(col):
    for attempt in range(2):
        try:
            return set(col.get(include=[])["ids"])
        except Exception as e:
            print(f"  [get 失败] {str(e)[:60]} — 清队列重试", flush=True)
            purge_queue()
            time.sleep(1)
    return None


def add_ks(col, meta, embs, ks):
    col.add(ids=[meta[k]["id"] for k in ks],
            embeddings=embs[ks].tolist(),
            documents=[meta[k]["content"] for k in ks],
            metadatas=[{k2: meta[k][k2] for k2 in META_KEYS} for k in ks])


def fill_missing(meta, embs, total, max_sweeps=8):
    for sweep in range(max_sweeps):
        if not purge_queue():
            time.sleep(30)
            continue
        col = fresh_col()
        have = have_ids(col)
        if have is None:
            continue
        missing = [i for i, m in enumerate(meta) if m["id"] not in have]
        print(f"对账 sweep {sweep}: 缺 {len(missing)} / {total}", flush=True)
        if not missing:
            print("=== 完成：全部 id 在库 ===", flush=True)
            return True
        for i in range(0, len(missing), BATCH):
            ks = missing[i:i + BATCH]
            for attempt in range(3):
                try:
                    add_ks(col, meta, embs, ks)
                    break
                except Exception as e:
                    print(f"  [补 {attempt}] @{i}: {str(e)[:50]}", flush=True)
                    purge_queue()
                    time.sleep(2)
    print("!! 达到 sweep 上限仍有缺口", flush=True)
    return False


def main():
    meta = json.load(open("data/all_meta.json", encoding="utf-8"))
    embs = np.load("data/all_embeddings.npy")
    total = len(meta)
    t0 = time.time()

    for rounds in range(1, 801):
        if not purge_queue():
            print("!! 队列清不掉，60s 后重试", flush=True)
            time.sleep(60)
            continue
        col = fresh_col()
        have = have_ids(col)
        if have is None:
            print(f"round {rounds}: 读失败跳过", flush=True)
            continue
        pending = [i for i, m in enumerate(meta) if m["id"] not in have]
        if not pending:
            print("全部 id 已在库，结束", flush=True)
            break
        wrote = 0
        died = False
        for i in range(0, len(pending), BATCH):
            ks = pending[i:i + BATCH]
            try:
                add_ks(col, meta, embs, ks)
                wrote += len(ks)
            except Exception as e:
                print(f"round {rounds}: 窗口死亡 @{i}（{str(e)[:40]}），"
                      f"本窗已写 {wrote} 条", flush=True)
                died = True
                break
        if not died:
            continue  # pending 清零会在下轮 have 检查里结束
        if rounds % 10 == 0 or wrote == 0:
            print(f"  进度: round {rounds}, 本窗 {wrote} 条, "
                  f"累计 {time.time()-t0:.0f}s", flush=True)
        if wrote == 0 and rounds > 20:
            print("!! 连续空窗，转对账", flush=True)
            break

    ok = fill_missing(meta, embs, total)
    print(f"总用时 {time.time()-t0:.0f}s | 结果 {'成功' if ok else '有缺口'}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
