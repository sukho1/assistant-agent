# -*- coding: utf-8 -*-
"""手动补齐 chroma 建库迁移（修复 code 14: unable to open database file）。

背景：chromadb 1.5.9 的 rust Bindings 在本机「新建数据库」时初始化失败，
只会留下一个含 acquire_write 锁行、 migrations 为空的半成品
chroma.sqlite3。本脚本：
  1. 清掉死锁行；
  2. 按 metadb -> sysdb -> embeddings_queue 顺序执行
     .venv/Lib/site-packages/chromadb/migrations/<dir>/*.sql；
  3. 登记 migrations 表（hash = md5(read_text() 规范化 LF 后的 utf-8，
     与 chroma rust 的校验一致）。
之后 chroma 即可正常打开该库（实测写入/查询均正常）。
"""
import glob
import hashlib
import os
import sqlite3
import sys

import config


def main():
    db = os.path.join(config.CHROMA_DIR, "chroma.sqlite3")
    if not os.path.exists(db):
        print("chroma.sqlite3 不存在——先运行一次 index.py 让它创建基础库")
        sys.exit(1)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("DELETE FROM acquire_write")

    base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        ".venv", "Lib", "site-packages", "chromadb", "migrations")
    applied = 0
    for d in ("metadb", "sysdb", "embeddings_queue"):
        for fp in sorted(glob.glob(os.path.join(base, d, "*.sql"))):
            fn = os.path.basename(fp)
            version = int(fn.split("-")[0])
            sql = open(fp, encoding="utf-8").read()  # read_text 规范化 LF
            h = hashlib.md5(sql.encode("utf-8")).hexdigest()
            try:
                conn.executescript(sql)
            except sqlite3.OperationalError as e:
                if "already exists" in str(e):
                    pass
                else:
                    raise
            conn.execute(
                "INSERT OR REPLACE INTO migrations (dir, version, filename, sql, hash)"
                " VALUES (?,?,?,?,?)", (d, version, fn, sql, h))
            applied += 1
    conn.commit()
    n = conn.execute("select count(*) from migrations").fetchone()[0]
    print(f"已应用/登记 {applied} 个迁移，migrations 表 {n} 条。chroma 现在可以打开了。")
    conn.close()


if __name__ == "__main__":
    main()
