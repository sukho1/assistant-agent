"""SessionStart hook: inject the counseling framework into the conversation context.

ZCode parses hook stdout as strict JSON; `additionalContext` is injected into
the conversation. On any failure we print nothing (empty output is a pass), so
a missing skill file or encoding issue never breaks session startup.
"""

import json
import re
import sys
from pathlib import Path

try:
    # 用户级 hook 对每个项目都会触发，用传入的项目根定位；无参数时回退脚本自身位置推导
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir():
        root = Path(sys.argv[1]).resolve()
    else:
        root = Path(__file__).resolve().parents[2]  # .zcode/hooks/x.py -> repo root
    sk = root / ".codex" / "skills" / "counseling" / "SKILL.md"
    text = sk.read_text(encoding="utf-8")
    text = re.sub(r"^---.*?---\n", "", text, flags=re.S).strip()
    payload = (
        "# counseling 框架（SessionStart hook 自动注入，已常驻上下文，无需再读文件）\n\n"
        + text
    )
    out = json.dumps({"additionalContext": payload}, ensure_ascii=False)
    sys.stdout.reconfigure(encoding="utf-8")
    print(out)
except Exception:
    sys.exit(0)
