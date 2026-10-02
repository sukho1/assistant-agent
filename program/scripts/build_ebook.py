#!/usr/bin/env python3
"""生成全站文集电子书：苏霍壹“马克思+庄子+心理学体系”文集（ebook.pdf）。

生成要求见仓库根目录《电子书生成要求.md》：目录 md 的系列（一级，“一、”）→
分组（二级，“（一）”）→ 文章 顺序；正文 Word 五号（10.5pt）；PDF 侧边书签大纲
（Edge --generate-pdf-document-outline，缺失时用 pypdf 按标题定位页面补写）。

用法：python program/scripts/build_ebook.py
"""
import html
import re
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_knowledge_site as bks  # noqa: E402

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CN_NUM = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

VERSION = "v2026.10.2.1"


def bold_chn_numbered(body_html: str) -> str:
    """作者手写的中文序号标题行（“一、……”“（一）……”开头）一律加粗。

    这类文章多为硬换行写法：整节是一个块，行间以 <br> 分隔。因此按 <br>
    逐行判断，只给命中中文序号模式的那一行加 <span class="chn-h">，
    同段其他行不受影响。处理 <p>/<li>/<blockquote> 三类块（列表松散写法
    的 <li> 内含 <p>，由 <p> 一轮处理，容器轮跳过以防重复包裹）。
    """
    br_pat = re.compile(r"(<br\s*/?>)")
    line_pat = re.compile(r"^(?:[一二三四五六七八九十百]+、|（[一二三四五六七八九十百]+）)")

    def bold_lines(inner):
        parts = br_pat.split(inner)
        out, changed = [], False
        for seg in parts:
            if br_pat.fullmatch(seg) or 'class="chn-h"' in seg:
                out.append(seg)
                continue
            text = re.sub(r"<[^>]+>", "", seg).strip()
            if line_pat.match(text):
                out.append(f'<span class="chn-h">{seg}</span>')
                changed = True
            else:
                out.append(seg)
        return "".join(out) if changed else None

    def make_repl(tag):
        def repl(m):
            inner = m.group(2)
            if tag in ("li", "blockquote") and re.search(r"<(?:p|li|blockquote)[ >]", inner):
                return m.group(0)  # 容器：交给内部块单独处理
            new_inner = bold_lines(inner)
            return f"<{tag}>{new_inner}</{tag}>" if new_inner is not None else m.group(0)
        return repl

    for tag in ("p", "li", "blockquote"):
        body_html = re.sub(rf"<({tag})>(.*?)</\1>", make_repl(tag),
                           body_html, flags=re.S)
    return body_html


def cn(i: int) -> str:
    return CN_NUM[i] if i < len(CN_NUM) else str(i + 1)


def block_headings(body_html: str) -> str:
    """正文小节标题降为带样式的 div：不进入书签大纲，视觉样式不变。"""
    body_html = re.sub(r"<h([1-6])(\s[^>]*)?>",
                       lambda m: f'<div class="bh{m.group(1)}">', body_html)
    return re.sub(r"</h[1-6]>", "</div>", body_html)


PRINT_CSS = """
@page { size:A4; margin:20mm 17mm; }
* { box-sizing:border-box; }
body { font-family:"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif;
  font-size:10.5pt; line-height:2.0; color:#222; margin:0; } /* 正文 Word 五号，行距 2.0 */
a { color:inherit; text-decoration:none; }
.cover { page-break-after:always; text-align:center; padding-top:150px; }
.cover h1 { font-size:24pt; font-weight:800; letter-spacing:.02em; line-height:1.7; margin:0 0 18px; }
.cover .sub { font-size:13pt; color:#666; margin:6px 0; }
.cover .meta { margin-top:120px; color:#888; font-size:10pt; line-height:2; }
nav.toc { page-break-after:always; }
.toc-title { font-size:20pt; font-weight:700; border-bottom:2px solid #b8860b; padding-bottom:8px; }
.toc-h2 { font-size:14pt; font-weight:700; margin:1.4em 0 .3em; color:#8a5a2b; }
.toc-h3 { font-size:11.5pt; font-weight:700; margin:1em 0 .2em; color:#555; }
nav.toc ul { list-style:none; margin:.2em 0; padding-left:1.4em; }
nav.toc li { margin:2px 0; }
/* 一二级标题都另起一页；标题后紧接文章（相邻选择器抑制多余分页） */
section.part, .grp { page-break-before:always; }
section.part + .grp, .grp + .art { page-break-before:auto; }
section.part h2 { font-size:18pt; font-weight:800; margin:30px 0 14px;
  border-bottom:2px solid #b8860b; padding-bottom:10px; letter-spacing:.05em; }
.grp h3 { font-size:13.5pt; font-weight:800; margin:0 0 12px; color:#8a5a2b; }
.art { page-break-before:always; }
.crumb { color:#999; font-size:9pt; letter-spacing:.05em; margin-bottom:2px; }
.art h4 { font-size:16.5pt; font-weight:800; line-height:1.4; margin:0 0 16px;
  border-bottom:1px solid #ddd; padding-bottom:10px; }
/* 正文小节标题降为 div（不进书签大纲），样式保持 */
.art .bh1 { font-size:14pt; font-weight:700; margin:1.6em 0 .4em; }
.art .bh2 { font-size:13pt; font-weight:700; margin:1.6em 0 .4em; border-left:4px solid #b8860b; padding-left:9px; }
.art .bh3 { font-size:11.5pt; font-weight:700; margin:1.3em 0 .3em; }
.art .bh4, .art .bh5, .art .bh6 { font-size:11pt; font-weight:700; margin:1.1em 0 .3em; }
.art p { text-align:justify; margin:1em 0; } /* 段间距在 2.0 行距基础上另行加大 */
.art p.chn-h { font-weight:700; }
.art blockquote { margin:1em 0; padding:2px 14px; color:#666; border-left:3px solid #ccc; }
.art img { max-width:100%; }
.art table { border-collapse:collapse; width:100%; font-size:9.5pt; }
.art th, .art td { border:1px solid #ccc; padding:4px 8px; }
.art code, .art pre { font-family:Consolas,monospace; font-size:9pt; background:#f5f2ec; }
.art pre { padding:10px; overflow-wrap:break-word; white-space:pre-wrap; }
"""

BOOK_NAME = "苏霍壹“马克思+庄子+心理学体系”文集"


def edge_exe() -> str:
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    raise RuntimeError("未找到 msedge.exe，请确认已安装 Microsoft Edge")


def print_pdf(edge: str, html_uri: str, out: Path) -> None:
    """调用 Edge 无头打印。先删旧文件；Edge 对大文档常不自动退出，
    按“出现新文件且大小稳定 30 秒”判定完成并自动终止 Edge。"""
    if out.exists():
        out.unlink()
    cmd = [edge, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
           "--generate-pdf-document-outline", f"--print-to-pdf={out}", html_uri]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    last, stable, seen_write = -1, 0, False
    for _ in range(360):  # 最多约 60 分钟
        time.sleep(10)
        if out.exists():
            sz = out.stat().st_size
            if sz != last:
                seen_write, stable = True, 0
            elif seen_write and sz > 0:
                stable += 1
            last = sz
            if seen_write and stable >= 3:
                break
    time.sleep(3)
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except Exception:
            proc.kill()
    if not out.exists():
        raise RuntimeError("Edge 未产出 PDF")


def postprocess(pdf_path: Path, items) -> None:
    """收尾：书签大纲（Edge 未生成时用 pypdf 补写）+ 右下角页码（封面不加）。"""
    from pypdf import PdfReader, PdfWriter
    from io import BytesIO
    r = PdfReader(str(pdf_path))
    writer = PdfWriter()
    writer.append(r)
    if not r.outline:
        pages_txt = [(p.extract_text() or "").replace(" ", "").replace("\n", "")
                     for p in r.pages]
        pos, parents = 0, {}
        for level, title in items:
            t = title.replace(" ", "")
            page = None
            for i in range(pos, len(pages_txt)):
                if t not in pages_txt[i]:
                    continue
                if pos == 0 and "目录" in pages_txt[i]:
                    continue  # 第一项跳过文内目录页，落回正文
                page, pos = i, i
                break
            if page is None:
                continue
            parents[level] = writer.add_outline_item(title, page, parent=parents.get(level - 1))
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=(595.27, 841.89))
    n = len(r.pages)
    for i in range(2, n + 1):
        c.setFont("Helvetica", 9)
        c.drawRightString(595.27 - 42, 26, str(i))
        c.showPage()
    c.save()
    overlay = PdfReader(BytesIO(buf.getvalue()))
    for idx in range(1, n):
        writer.pages[idx].merge_page(overlay.pages[idx - 1])
    tmp = pdf_path.with_suffix(".tmp.pdf")
    with open(tmp, "wb") as f:
        writer.write(f)
    tmp.replace(pdf_path)
    return True


def main() -> None:
    entries = []
    for slug, _, _ in bks.SERIES:
        folder = bks.KNOWLEDGE / slug
        if not folder.exists():
            continue
        for md_path in sorted(folder.glob("*.md")):
            md_text = bks.FRONTMATTER.sub("", md_path.read_text(encoding="utf-8"))
            title = bks.article_title(md_path, md_text)
            body = bks.strip_leading_h1(bks.pandoc(md_text), title)
            entries.append({"slug": slug, "file": md_path.stem,
                            "title": title, "body": body})
    layout = bks.build_layout(entries)

    # ---- 按目录顺序渲染：一级“一、”系列，二级“（一）”分组，文章不编号 ----
    rendered, toc, outline = [], [], []
    seen_key = set()
    s_no = a_no = 0
    for slug, label, _ in bks.ordered_series():
        if slug not in layout:
            continue
        h2 = f"{cn(s_no)}、{label}"
        s_no += 1
        outline.append((2, h2))
        s_toc = []
        for gi, (glabel, members) in enumerate(layout[slug]):
            h3 = f"（{cn(gi)}）{glabel}"
            outline.append((3, h3))
            g_toc = []
            for e in members:
                nt = bks._norm(e["title"])
                if nt in seen_key:
                    continue
                seen_key.add(nt)
                e["aid"] = f"a{a_no:04d}"
                a_no += 1
                e["slabel"], e["glabel"] = label, glabel
                e["sh2"], e["gh3"] = h2, h3
                e["body"] = bold_chn_numbered(block_headings(e["body"]))
                rendered.append(e)
                outline.append((4, e["title"]))
                g_toc.append(f'<li><a href="#{e["aid"]}">{html.escape(e["title"])}</a></li>')
            if g_toc:
                s_toc.append(f'<div class="toc-h3">{html.escape(h3)}（{len(g_toc)}）</div><ul>'
                             + "".join(g_toc) + "</ul>")
        if s_toc:
            toc.append(f'<div class="toc-h2">{html.escape(h2)}</div>' + "".join(s_toc))

    arts = []
    open_series = open_group = None
    for e in rendered:
        if e["slabel"] != open_series:
            open_series, open_group = e["slabel"], None
            arts.append(f'<section class="part"><h2>{html.escape(e["sh2"])}</h2></section>')
        if e["gh3"] != open_group:
            open_group = e["gh3"]
            arts.append(f'<div class="grp"><h3>{html.escape(e["gh3"])}</h3></div>')
        arts.append(
            f'<section class="art" id="{e["aid"]}">'
            f'<div class="crumb">{html.escape(e["slabel"])} · {html.escape(e["glabel"])}</div>'
            f'<h4>{html.escape(e["title"])}</h4>{e["body"]}</section>')

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>{BOOK_NAME}</title><style>{PRINT_CSS}</style></head>
<body>
<section class="cover">
  <h1>苏霍壹<br>“马克思+庄子+心理学体系”文集</h1>
  <p class="sub">马克思 + 庄子 + 心理学 · 人人本自具足</p>
  <p class="sub">共 {len(rendered)} 篇 · 按体系目录编排</p>
  <div class="meta">
    https://sukho1.github.io/ma-zhuang/<br>
    版本 {VERSION}<br>
    内容遵循 CC BY-NC-SA 4.0<br>
    生成日期 {date.today().isoformat()}
  </div>
</section>
<nav class="toc"><div class="toc-title">目录</div>{"".join(toc)}</nav>
{"".join(arts)}
</body></html>"""

    tmp = Path(tempfile.gettempdir()) / "mazhuang_ebook.html"
    tmp.write_text(doc, encoding="utf-8")
    out = bks.OUT / (BOOK_NAME + ".pdf")
    print(f"printing {len(rendered)} articles -> {out} ...", flush=True)
    print_pdf(edge_exe(), tmp.as_uri(), out)

    postprocess(out, outline)
    from pypdf import PdfReader
    r = PdfReader(str(out))
    flat = []

    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it)
            else:
                flat.append(it.title)
    walk(r.outline)
    print(f"done: {out}（{len(r.pages)} 页，{out.stat().st_size / 1048576:.1f} MB，"
          f"书签 {len(flat)} 条）", flush=True)


if __name__ == "__main__":
    main()
