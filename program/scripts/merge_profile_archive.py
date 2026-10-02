# -*- coding: utf-8 -*-
"""一次性迁移：把「综合档案 + 四个维度」两套目录合并为单套档案。

机械格式转换，不改写任何分析文字，只做：
  - 标题层级调整（维度块降一级，去掉冗余 H1）
  - 板块拼装（维度内容作为板块并入同一个文件）
  - 旧路径引用改写（comprehensive/… → …）

目标结构（user-data/user_profile/ 下，均为隐私目录、不进 git）：
    overview.md  last-update.md  weekly/  monthly/  quarterly/  annual/

用法：
    python program/scripts/merge_profile_archive.py stage    # 生成到 _stage/，不动原文件
    python program/scripts/merge_profile_archive.py commit   # 原目录移入 _legacy/，_stage/ 上架
    python program/scripts/merge_profile_archive.py revert   # 从 _legacy/ 还原，撤销迁移
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROF = ROOT / "user-data" / "user_profile"
COMP = PROF / "comprehensive"
DIM_ROOT = PROF / "four-dimensions"
DIMS = [("维1·元素（五要素）", DIM_ROOT / "dim1-elements"),
        ("维2·链接", DIM_ROOT / "dim2-links"),
        ("维3·业障", DIM_ROOT / "dim3-karma")]
PERIODS = ("weekly", "monthly", "quarterly", "annual")
STAGE = PROF / "_stage"
LEGACY = PROF / "_legacy"
NEW_DIRS = tuple(PERIODS)

FM_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
H1_RE = re.compile(r"^#\s+.*$", re.M)
H1_RENAME = [("综合周记", "周记"), ("综合月记", "月记"), ("综合季记", "季记"),
             ("综合年记", "年记"), ("综合档案", "用户档案总览")]
PATH_FIX = [
    ("comprehensive/annual/", "annual/"), ("comprehensive/monthly/", "monthly/"),
    ("comprehensive/quarterly/", "quarterly/"), ("comprehensive/weekly/", "weekly/"),
    ("four-dimensions/dim1-elements/", ""), ("four-dimensions/dim2-links/", ""),
    ("four-dimensions/dim3-karma/", ""), ("four-dimensions/", ""),
]


def split_fm(text: str) -> tuple[str, str]:
    m = FM_RE.match(text)
    return (m.group(0), text[m.end():]) if m else ("", text)


def rename_h1(body: str) -> str:
    def repl(m: re.Match) -> str:
        line = m.group(0)
        for a, b in H1_RENAME:
            line = line.replace(a, b)
        return line
    return H1_RE.sub(repl, body, count=1)


def demote(body: str, levels: int = 1) -> str:
    out = []
    for ln in body.splitlines():
        m = re.match(r"^(#{1,5})(\s)", ln)
        out.append("#" * (len(m.group(1)) + levels) + ln[m.end(1):] if m else ln)
    return "\n".join(out)


def fix_refs(text: str) -> str:
    for a, b in PATH_FIX:
        text = text.replace(a, b)
    return re.sub(r"\bcomprehensive\b\s*", "", text)


def drop_first_h1(body: str) -> str:
    return H1_RE.sub("", body, count=1).lstrip("\n")


def dim_block(label: str, dim_file: Path) -> str | None:
    if not dim_file.exists():
        return None
    _, dbody = split_fm(dim_file.read_text(encoding="utf-8"))
    body = demote(fix_refs(drop_first_h1(dbody))).strip("\n")
    return f"\n## {label}\n\n{body}\n"


def build_period_files() -> dict[str, int]:
    counts = {p: 0 for p in PERIODS}
    for period in PERIODS:
        src_dir = COMP / period
        if not src_dir.is_dir():
            continue
        (STAGE / period).mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.glob("*.md")):
            fm, body = split_fm(src.read_text(encoding="utf-8"))
            out = fm + rename_h1(fix_refs(body)).rstrip("\n") + "\n"
            for label, dim_dir in DIMS:
                block = dim_block(label, dim_dir / period / src.name)
                if block:
                    out += block
            (STAGE / period / src.name).write_text(out, encoding="utf-8")
            counts[period] += 1
    return counts


def build_overview() -> str:
    """总览：4 个 overview 合并为一个文件。
    主体沿用 comprehensive/overview.md（事实区 + 分析区），三个维度 overview
    全文作为维度板块附在其后（标题降一级），与周期文件同一拼装方式。"""
    comp_text = (COMP / "overview.md").read_text(encoding="utf-8")
    cfm, cbody = split_fm(comp_text)
    head = fix_refs(rename_h1(cbody)).rstrip("\n")
    head = head.replace(
        "# 用户档案总览",
        "# 用户档案总览\n\n> 单文件总览。周期文件见 `weekly/ monthly/ quarterly/ annual/`；"
        "维度详情见文末三个维度板块。",
        1,
    )
    out = [cfm, head, "\n"]
    for label, dim_dir in DIMS:
        dtext = (dim_dir / "overview.md").read_text(encoding="utf-8")
        _, dbody = split_fm(dtext)
        body = demote(drop_first_h1(dbody)).strip("\n")
        out.append(f"\n## {label}\n\n{body}\n")
    return "".join(out)


def stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    counts = build_period_files()
    (STAGE / "overview.md").write_text(build_overview(), encoding="utf-8")
    total = sum(counts.values())
    print("staged period files:", counts, "total", total)
    print("staged overview:", (STAGE / "overview.md").stat().st_size, "bytes")


def commit() -> None:
    if not STAGE.is_dir():
        raise SystemExit("先运行 stage")
    if LEGACY.exists():
        raise SystemExit(f"{LEGACY} 已存在，迁移可能已执行；如需还原请用 revert")
    LEGACY.mkdir()
    for d in NEW_DIRS:
        if (PROF / d).exists():
            raise SystemExit(f"{PROF / d} 已存在，先清理再迁移")
    shutil.move(str(COMP), str(LEGACY / "comprehensive"))
    shutil.move(str(DIM_ROOT), str(LEGACY / "four-dimensions"))
    shutil.move(str(PROF / "overview.md"), str(LEGACY / "overview.nav.md"))
    for d in NEW_DIRS:
        shutil.move(str(STAGE / d), str(PROF / d))
    shutil.move(str(STAGE / "overview.md"), str(PROF / "overview.md"))
    shutil.rmtree(STAGE)
    print("committed; 原目录在", LEGACY)


def revert() -> None:
    if not LEGACY.is_dir():
        raise SystemExit("没有 _legacy 可还原")
    for d in NEW_DIRS:
        if (PROF / d).exists():
            shutil.rmtree(PROF / d)
    if (PROF / "overview.md").exists():
        (PROF / "overview.md").unlink()
    shutil.move(str(LEGACY / "comprehensive"), str(COMP))
    shutil.move(str(LEGACY / "four-dimensions"), str(DIM_ROOT))
    shutil.move(str(LEGACY / "overview.nav.md"), str(PROF / "overview.md"))
    shutil.rmtree(LEGACY)
    print("reverted")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stage"
    {"stage": stage, "commit": commit, "revert": revert}.get(cmd, stage)()
