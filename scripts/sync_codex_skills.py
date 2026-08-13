#!/usr/bin/env python3
"""Generate the Codex skill tree from the Claude skill tree.

The source of truth is ``.claude/skills/``. This script rebuilds
``.codex/skills/`` deterministically so the two platform trees stay in sync
without maintaining duplicated content by hand.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / ".claude" / "skills"
DEST = ROOT / ".codex" / "skills"


def transform_markdown(text: str) -> str:
    """Adapt Claude-specific skill text to Codex conventions."""
    text = text.replace(".claude/skills", ".codex/skills")

    # Skill("name") -> read and execute the corresponding Codex SKILL.md.
    text = re.sub(
        r"`Skill\(\"([^\"]+)\"\)`",
        lambda match: f"`读取并执行 .codex/skills/{match.group(1)}/SKILL.md`",
        text,
    )

    # Generic Claude tool names used in the instruction prose.
    text = text.replace("调用 Skill 工具", "读取 Skill 文件")
    text = text.replace("不重复调用 Skill 工具", "不重复读取 Skill 文件")
    text = text.replace("重新调用 Skill 工具", "重新读取 Skill 文件")
    text = text.replace("Write/Edit/Bash", "写文件/编辑/shell")
    text = text.replace("Bash 工具写", "shell 写")
    text = re.sub(r"\bGlob\b", "文件搜索（如 `rg --files` 或 `rg`）", text)

    # The profile-update skill describes Claude's file-editing tools.
    text = text.replace(
        "Write 工具可能要求先 Read",
        "apply_patch 可能要求文件已存在",
    )
    text = text.replace(
        "用 Bash `touch path` 创建空文件后 Read 再 Write",
        "先用 shell 创建空文件，再读取并编辑",
    )
    text = text.replace(
        "Bash heredoc 仅限创建新文件",
        "shell heredoc 仅限创建新文件",
    )
    text = text.replace(
        "更新已有文件必须 Edit",
        "更新已有文件必须使用 apply_patch",
    )

    return text


def should_transform(path: Path) -> bool:
    return path.suffix.lower() == ".md"


def rebuild() -> None:
    if DEST.exists():
        shutil.rmtree(DEST)

    shutil.copytree(SOURCE, DEST)

    for path in sorted(DEST.rglob("*")):
        if not path.is_file() or not should_transform(path):
            continue

        original = path.read_text(encoding="utf-8")
        transformed = transform_markdown(original)
        if transformed != original:
            path.write_text(transformed, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    rebuild()
    print(f"synced {SOURCE} -> {DEST}")
