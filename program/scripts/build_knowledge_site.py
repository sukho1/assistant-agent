#!/usr/bin/env python3
"""Generate the 马庄心理学 static site from knowledge/ markdown.

Usage:
    python program/scripts/build_knowledge_site.py [output_dir]

Output defaults to <repo-parent>/ma-zhuang/ (deployed as the project site
https://sukho1.github.io/ma-zhuang/). Requires pandoc on PATH.
Layout: sticky top bar (brand left, full-text search right), collapsible
left sidebar listing every series (folder) and article, article pages with
a separated title header. Re-run after knowledge/ changes and push the
output repo.
"""

import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent.parent.parent
KNOWLEDGE = ROOT / "knowledge"
# 站点展示结构（系列顺序→二级分组→文章顺序）的唯一来源：用户手工维护的目录文档
CATALOG_MD = KNOWLEDGE / "文章目录.md"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / "ma-zhuang"

SITE_TITLE = "马庄心理学"
SITE_SUBTITLE = "马克思 + 庄子 + 心理学 · 人人本自具足"
REPO_URL = "https://github.com/sukho1/assistant-agent"

# 正式站（2026-10-15）：文章站已迁到主站由 Cloudflare Worker 提供，本仓库这套 GitHub Pages
# 站点保留下来只为承接既有外链。内容两边同源，所以每页必须加 canonical 指向新站，
# 否则两个域名同一批文章会被搜索引擎判成重复内容。
# 新站的文章页是**无扩展名**形态（实测 /x.html 会 307 跳到 /x）。
NEW_SITE_BASE = "https://chat.justlinknow.com/articles/"

# 评论走 giscus：数据存放在站点仓库的 GitHub Discussions，无后端、零成本。
# 前提：在 https://github.com/apps/giscus 安装 giscus App 并授权本仓库。
GISCUS = {
    "repo": "sukho1/sukho1.github.io",
    "repo_id": "R_kgDOP4tq-Q",
    "category": "Announcements",
    "category_id": "DIC_kwDOP4tq-c4DFxkl",
}
# 自定义 giscus 主题：官方亮/暗变量 + 隐藏 👎/😕 两个反应按钮（见仓库内两个 css）
GISCUS_THEMES = {
    "light": "https://sukho1.github.io/ma-zhuang/giscus-light.css",
    "dark": "https://sukho1.github.io/ma-zhuang/giscus-dark.css",
}

# 综合热度 = 点赞×1 + 评论×2 + 点击×0.01，构建时从 giscus 数据仓库（GitHub
# Discussions）拉取点赞/评论数，烘焙进静态页面决定侧边栏与主页的排列。
# 纯静态站无法实时计数，每次重新构建即刷新；点击数暂无计数来源（接入
# GoatCounter 等服务后并入），gh 或网络不可用时自动降级为全 0。
HEAT_W_LIKE = 1
HEAT_W_COMMENT = 2
HEAT_W_VIEW = 0.01

ABOUT_TEXT = ("马克思+庄子+心理学，这个时代的版本答案，我们普通人在赛博朋克原子化时代"
              "生存的社科和心理心灵体系。一套完整、实战、清爽的体系。以心理学为基座，"
              "人本主义、存在主义这两个心灵哲学为支柱，马克思、庄子这两个社科哲学为指导思想。"
              "谈心理、心灵、开悟、活在当下。")
OVERVIEW_ARTICLE = "我的马克思+庄子+心理学体系概述"
# 姊妹站：马克思主义主题文集（与 marxism 站 about 栏的马庄链接互为镜像）
SISTER_SITE = ("https://sukho1.github.io/marxism/", "苏霍壹马克思主义系列文集")
# 各平台账号；小红书/抖音/快手暂用站内搜索页兜底，拿到主页直链后直接替换 URL
SOCIALS = [
    ("📕", "小红书", "https://www.xiaohongshu.com/search_result?keyword=" + quote("苏霍壹")),
    ("🔷", "知乎", "https://www.zhihu.com/people/sukho1"),
    ("🐙", "GitHub", "https://github.com/sukho1"),
    ("💚", "公众号", "https://weixin.sogou.com/weixin?type=1&query=" + quote("苏霍壹")),
    # 注：微信公众号没有网页版主页，此链接指向搜狗微信的公众号搜索结果页
    ("🎬", "豆瓣", "https://www.douban.com/people/4075628/"),
    ("📺", "B站", "https://space.bilibili.com/42516170"),
    ("𝕏", "推特", "https://x.com/sukho1_"),
    ("🎵", "抖音", "https://www.douyin.com/search/" + quote("苏霍壹")),
    ("🎥", "快手", "https://www.kuaishou.com/search/video?searchKey=" + quote("苏霍壹")),
]

SERIES = [
    ("zhuangzi-series", "庄子系列", "本自具足、活在当下、逍遥"),
    ("link-series", "链接系列", "链接自己、他人、社会、历史、世界、自然"),
    ("karma-series", "业障系列", "认识业障：内在防御与外在处境"),
    ("marx-series", "马克思系列", "历史唯物主义视角下的心理与社会"),
    ("self-psychology", "自体与心理学系列", "科胡特、温尼科特与自体疗愈"),
]

FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n+", re.S)
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)
TAG = re.compile(r"<[^>]+>")


def pandoc(md_text: str) -> str:
    p = subprocess.run(["pandoc", "-f", "gfm+hard_line_breaks", "-t", "html5"],
                       input=md_text.encode("utf-8"), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[:400])
    return p.stdout.decode("utf-8")


def article_title(md_path: Path, md_text: str) -> str:
    m = H1.search(md_text)
    if m:
        title = TAG.sub("", pandoc(m.group(1))).strip()
        if title:
            return title
    return md_path.stem


def excerpt(md_text: str, limit: int = 100) -> str:
    body = "\n".join(line for line in md_text.splitlines() if not line.startswith("#"))
    text = html.unescape(re.sub(r"\s+", "", TAG.sub("", pandoc(body))))
    return text[:limit]


def strip_leading_h1(body_html: str, title: str) -> str:
    """Remove the body's own leading <h1> when it duplicates the page title."""
    m = re.match(r"\s*<h1[^>]*>(.*?)</h1>", body_html, re.S)
    if m:
        text = html.unescape(TAG.sub("", m.group(1))).strip()
        if text == title:
            return body_html[m.end():]
    return body_html


def fetch_heat() -> dict:
    """从 GitHub Discussions 拉取各页的点赞/评论数，返回 {路径key: 热度}。

    giscus 的 mapping=pathname 会用页面路径（百分号编码）作为 discussion 标题；
    站点迁移前路径无 ma-zhuang/ 前缀，归一化后新旧讨论并入同一篇文章的热度。
    """
    query = ("query { repository(owner: \"sukho1\", name: \"sukho1.github.io\") {"
             " discussions(first: 100) { nodes { title"
             " reactions(first: 1) { totalCount }"
             " comments(first: 30) { totalCount nodes { body reactions(first: 1) { totalCount } } }"
             " } } } }")
    try:
        p = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query],
                           capture_output=True, timeout=90)
        if p.returncode != 0:
            raise RuntimeError(p.stderr.decode("utf-8", "replace")[:200])
        nodes = json.loads(p.stdout)["data"]["repository"]["discussions"]["nodes"]
    except Exception as exc:
        print(f"!! 热度数据拉取失败，本版按 0 处理：{exc}")
        return {}

    def disc_key(title: str) -> str:
        path = unquote(title).strip("/")
        if path.startswith("ma-zhuang/"):
            path = path[len("ma-zhuang/"):]
        # 旧站 URL 无 .html 扩展名，现行站有，统一去掉再对齐
        return path[:-5] if path.endswith(".html") else path

    heat = {}
    for n in nodes:
        likes = n["reactions"]["totalCount"]
        comments = n["comments"]["totalCount"]
        for c in n["comments"]["nodes"]:
            if "giscus" in c["body"] and "metadata" in c["body"]:
                comments -= 1  # giscus 内部元数据评论不计
            likes += c["reactions"]["totalCount"]
        views = 0  # 点击数：接入计数服务（GoatCounter 等）后在此并入各页浏览量
        heat[disc_key(n["title"])] = (likes * HEAT_W_LIKE
                                      + comments * HEAT_W_COMMENT
                                      + views * HEAT_W_VIEW)
    return heat


def heat_badge(e) -> str:
    return (f'<span class="heat">🔥 {int(round(e["heat"]))}</span>'
            if e["heat"] > 0 else "")


def _norm(text: str) -> str:
    """忽略空白与标点差异，用于目录条目与文章标题的匹配。"""
    return re.sub(r"[\W\s_]+", "", text).lower()


_CATALOG = None


def catalog_data():
    """解析 文章目录.md：## 系列（一级）→ ### 分组（二级）→ `- 标题`（文章顺序）。

    返回 (系列slug按文档顺序, {slug: [(分组名, [标题,...])]})；
    未识别的系列忽略，条目兼容 `[标题](路径)` 链接写法。
    """
    global _CATALOG
    if _CATALOG is None:
        slug_by_label = {label: slug for slug, label, _ in SERIES}
        order, groups = [], {}
        cur = None
        if CATALOG_MD.exists():
            for line in CATALOG_MD.read_text(encoding="utf-8").splitlines():
                m2 = re.match(r"^##\s+(.+?)\s*$", line)
                m3 = re.match(r"^###\s*(.+?)\s*$", line)
                mi = re.match(r"^-\s*(.+?)\s*$", line)
                if m2:
                    cur = slug_by_label.get(m2.group(1).strip())
                    if cur is not None and cur not in groups:
                        order.append(cur)
                        groups[cur] = []
                elif m3 and cur is not None:
                    groups[cur].append((m3.group(1).strip(), []))
                elif mi and cur is not None and groups.get(cur):
                    text = mi.group(1).strip()
                    if not re.search(r"\w", text, re.UNICODE):
                        continue  # 跳过 --- 之类的分隔线
                    mlink = re.match(r"\[(.+?)\]", text)
                    if mlink:
                        text = mlink.group(1)
                    groups[cur][-1][1].append(text)
        _CATALOG = (order, groups)
    return _CATALOG


def ordered_series():
    """系列按目录 md 中的出现顺序排列（未出现在 md 中的排最后）。"""
    order, _ = catalog_data()
    rows = list(SERIES)
    rows.sort(key=lambda s: order.index(s[0]) if s[0] in order else len(order))
    return rows


_LAYOUT = None


def build_layout(entries):
    """按目录 md 一次性构建全站展示结构（站点只展示 md 列出的内容）。

    - 标题匹配优先取本系列文件夹内的同名拷贝，其次精确匹配、最后模糊包含；
    - md 在多个章节列出同一文章时，各章节都展示（跨系列编排照常支持）；
    - 同一章节内重复条目只保留第一处；不发明任何分组。
    """
    global _LAYOUT
    order, groups = catalog_data()
    layout = {slug: [] for slug, _, _ in SERIES}
    unshown = []
    for slug in order:
        for label, titles in groups.get(slug, []):
            members = []
            seen_in_section = set()
            for t in titles:
                nt = _norm(t)
                if not nt or nt in seen_in_section:
                    continue
                seen_in_section.add(nt)
                exact = [e for e in entries if _norm(e["title"]) == nt]
                fuzzy = []
                if not exact and len(nt) >= 4:
                    fuzzy = [e for e in entries
                             if nt in _norm(e["title"]) or _norm(e["title"]) in nt]
                pick = None
                for c in exact + fuzzy:
                    if c["slug"] == slug:
                        pick = c
                        break
                if pick is None and exact + fuzzy:
                    pick = (exact + fuzzy)[0]
                if pick is None:
                    unshown.append(f"{slug}/{label}/{t}")
                    continue
                members.append(pick)
            if members:
                layout[slug].append((label, members))
    _LAYOUT = layout
    if unshown:
        print(f"!! 目录 md 中 {len(unshown)} 条匹配不到文章：")
        for m in unshown:
            print(f"   - {m}")
    return layout


def series_groups(entries, slug: str):
    """某系列的 [(分组名, [entry,...]), ...]，由 build_layout 预先构建。"""
    return _LAYOUT.get(slug, []) if _LAYOUT else []


def card_html(e) -> str:
    return (f'<a href="{quote(e["slug"])}/{quote(e["file"])}.html">'
            f'<span class="t">{html.escape(e["title"])}{heat_badge(e)}</span>'
            f'<span class="excerpt">{html.escape(e["excerpt"])}</span></a>')


def build_sidebar(entries, prefix: str, active_series: str, active_file: str) -> str:
    parts = ['<aside class="sidebar" id="sidebar"><nav>']
    for slug, label, _ in ordered_series():
        groups = series_groups(entries, slug)
        if not groups:
            continue
        total = sum(len(m) for _, m in groups)
        parts.append(f'<details open><summary>'
                     f'<span class="s-name">{html.escape(label)}</span>'
                     f'<span class="s-count">{total}</span></summary>')
        for glabel, members in groups:
            g_open = (" open" if slug == active_series and
                      any(e["slug"] == active_series and e["file"] == active_file
                          for e in members) else "")
            parts.append(f'<details class="s-g"{g_open}><summary>'
                         f'<span class="s-gname">{html.escape(glabel)}</span>'
                         f'<span class="s-count">{len(members)}</span></summary><ul>')
            for e in members:
                cur = (' class="current"' if (e["slug"] == active_series and
                                              e["file"] == active_file) else "")
                href = f"{prefix}{quote(e['slug'])}/{quote(e['file'])}.html"
                parts.append(f'<li><a href="{href}"{cur}>{html.escape(e["title"])}'
                             f'{heat_badge(e)}</a></li>')
            parts.append("</ul></details>")
        parts.append("</details>")
    parts.append("</nav>"
                 f'<a class="gb-link" href="{prefix}catalog.html">'
                 f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                 f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                 f'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>'
                 f'<span>文章目录</span></a>'
                 f'<a class="gb-link" href="{prefix}guestbook.html">'
                 f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                 f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
                 f'<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
                 f'<span>留言板</span></a></aside>')
    return "\n".join(parts)


def giscus_html() -> str:
    disc = f"https://github.com/{GISCUS['repo']}/discussions"
    return f"""<section class="comments">
<h2>留言</h2>
<p class="c-note">评论保存在 <a href="{disc}">GitHub Discussions</a>，留言需登录 GitHub 账号。</p>
<!-- 静态默认主题为亮色；手动亮/暗由 search.js 在 iframe load 后补推 -->
<script src="https://giscus.app/client.js"
  data-repo="{GISCUS['repo']}"
  data-repo-id="{GISCUS['repo_id']}"
  data-category="{GISCUS['category']}"
  data-category-id="{GISCUS['category_id']}"
  data-mapping="pathname"
  data-strict="0"
  data-reactions-enabled="1"
  data-emit-metadata="0"
  data-input-position="top"
  data-theme="{GISCUS_THEMES['light']}"
  data-lang="zh-CN"
  data-loading="lazy"
  crossorigin="anonymous"
  async></script>
</section>"""


def render_page(*, title_tag: str, body: str, entries, prefix: str,
                active_series: str = "", active_file: str = "",
                with_comments: bool = False, canonical: str = "") -> str:
    sidebar = build_sidebar(entries, prefix, active_series, active_file)
    # 留言板页没有新站对应物（新站的留言板要接本项目账号体系，尚未上线），所以不写 canonical——
    # 指向一个内容不同的页面，比不写更糟。
    canonical_tag = f'<link rel="canonical" href="{canonical}">\n' if canonical else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="only light">
<title>{title_tag}</title>
{canonical_tag}<link rel="stylesheet" href="{prefix}style.css?v={ASSET_VER}">
</head>
<body>
<header class="site-head">
  <button class="menu-btn" id="menuBtn" aria-label="目录">☰</button>
  <a class="brand" href="{prefix}index.html">{SITE_TITLE}</a>
  <span class="tagline">{SITE_SUBTITLE}</span>
  <button class="theme-btn" id="themeBtn" type="button" title="切换亮色/暗色">亮/暗</button>
  <div class="searchbox">
    <input id="q" type="search" placeholder="搜索" autocomplete="off">
    <div id="hits" class="hits"></div>
  </div>
</header>
<div class="layout">
{sidebar}
<main class="main">
{body}
{giscus_html() if with_comments else ""}
<footer class="foot">{SITE_TITLE} · 内容遵循 CC BY-NC-SA 4.0 · <a href="{REPO_URL}">GitHub</a></footer>
</main>
</div>
<script>window.SITE_PREFIX={json.dumps(prefix)};window.GISCUS_THEMES={json.dumps(GISCUS_THEMES)};</script>
<script src="{prefix}search.js?v={ASSET_VER}"></script>
</body>
</html>
"""


STYLE = """:root { --ink:#2b2620; --bg:#faf7f2; --card:#fff; --accent:#8a5a2b; --muted:#8a8377; --line:#e8e1d5; --head-h:58px; }
* { box-sizing:border-box; }
:root { color-scheme:only light; }
* { scrollbar-width:thin; scrollbar-color:var(--muted) transparent; }
::-webkit-scrollbar { width:9px; height:9px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:var(--muted); border-radius:5px; }
::-webkit-scrollbar-thumb:hover { background:var(--accent); }
html { scroll-behavior:smooth; }
body { margin:0; background:var(--bg); color:var(--ink);
  font:17.5px/1.85 "PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }
input,button,textarea,select { font:inherit; }

/* ---- top bar ---- */
.site-head { position:sticky; top:0; z-index:100; height:var(--head-h);
  display:flex; align-items:center; gap:14px; padding:0 22px;
  background:var(--card); border-bottom:1px solid var(--line); }
.menu-btn { display:none; border:1px solid var(--line); background:none; color:var(--ink);
  border-radius:8px; font-size:16px; line-height:1; padding:7px 10px; cursor:pointer; }
.brand { font-family:"PingFang SC","Microsoft YaHei","PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif;
  font-weight:700; font-size:18px; color:var(--accent); text-decoration:none; letter-spacing:.08em; }
.tagline { color:var(--muted); font-size:13px; letter-spacing:.02em;
  font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; white-space:nowrap; }
.theme-btn { margin-left:auto; border:1px solid var(--line); background:none; color:var(--muted);
  border-radius:999px; padding:6px 12px; font-size:13px; cursor:pointer; white-space:nowrap; }
.theme-btn:hover { color:var(--accent); border-color:var(--accent); }
.searchbox { position:relative; }
.searchbox input { width:240px; padding:8px 14px; font-size:14px; border:1px solid var(--line);
  border-radius:999px; outline:none; background:var(--bg); color:var(--ink);
  font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }
.searchbox input:focus { border-color:var(--accent); background:var(--card); }
.hits { position:absolute; right:0; top:calc(100% + 8px); width:min(360px,88vw); max-height:60vh;
  overflow:auto; display:none; background:var(--card); border:1px solid var(--line);
  border-radius:10px; box-shadow:0 8px 28px rgba(0,0,0,.10); }
.hits.show { display:block; }
.hits a { display:block; padding:9px 14px; text-decoration:none; color:var(--ink);
  font-size:14px; border-bottom:1px solid var(--line); }
.hits a:last-child { border-bottom:none; }
.hits a:hover { background:var(--bg); }
.hits a small { display:block; color:var(--muted); font-size:12px; }

/* ---- layout ---- */
.layout { display:flex; flex-wrap:nowrap; margin:0; gap:22px; padding:0 22px; align-items:flex-start; }
.sidebar { flex:0 0 236px; width:236px; position:sticky; top:var(--head-h);
  max-height:calc(100vh - var(--head-h) - 20px); overflow-y:auto; padding:14px 4px 30px 0; }
.sidebar nav { font-family:"PingFang SC","Microsoft YaHei","PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }
.sidebar details { border-bottom:1px solid var(--line); }
.sidebar details:last-child { border-bottom:none; }
.sidebar summary { list-style:none; display:flex; align-items:center; justify-content:space-between;
  padding:11px 8px; cursor:pointer; font-size:14.5px; font-weight:600; color:var(--ink); border-radius:8px; }
.sidebar summary::-webkit-details-marker { display:none; }
.sidebar summary::after { content:"+"; color:var(--muted); font-size:15px; }
.sidebar > nav > details[open] > summary::after,
.sidebar details.s-g[open] > summary::after { content:"−"; }
.sidebar summary:hover { color:var(--accent); }
.s-count { color:var(--muted); font-size:12px; font-weight:400; margin-left:6px; }
.sidebar summary { gap:6px; }
.sidebar summary .s-count { margin-left:auto; }
.sidebar ul { list-style:none; margin:0; padding:2px 0 10px; }
.sidebar li a { display:block; padding:5px 10px 5px 20px; font-size:14px; line-height:1.55;
  color:var(--muted); text-decoration:none; border-left:2px solid transparent; border-radius:0 8px 8px 0; }
.sidebar li a:hover { color:var(--accent); background:var(--bg); }
.sidebar li a.current { color:var(--accent); font-weight:600; border-left-color:var(--accent); background:var(--bg); }
/* 二级分组：可折叠，默认收起；当前文章所在分组自动展开 */
.sidebar details.s-g { border-bottom:none; }
.sidebar details.s-g summary { padding:6px 8px 6px 14px; font-size:13px; font-weight:500; color:var(--muted); }
.sidebar details.s-g[open] summary, .sidebar details.s-g summary:hover { color:var(--accent); }
.gb-link { display:flex; align-items:center; gap:8px; margin:14px 8px 4px; padding:9px 12px;
  border:1px solid var(--line); border-radius:10px; text-decoration:none; color:var(--ink);
  font-size:13.5px; font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }
.gb-link:hover { color:var(--accent); border-color:var(--accent); }
.gb-link svg { width:18px; height:18px; flex:none; }
.main { flex:1 1 0; min-width:0; max-width:840px; margin:0 auto; padding:18px 0 40px; }

/* ---- comments ---- */
.comments { margin-top:26px; }
.comments h2 { font-size:19px; margin:0; padding:0; border:none; }
.comments .c-note { color:var(--muted); font-size:13px; margin:4px 0 8px;
  font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }

/* ---- article ---- */
article { background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:34px 40px 40px; }
.a-head { padding-bottom:18px; margin-bottom:26px; border-bottom:1px solid var(--line); }
.a-series { font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; font-size:12.5px; color:var(--muted); letter-spacing:.05em; }
.a-series a { color:var(--muted); text-decoration:none; }
.a-series a:hover { color:var(--accent); }
h1.a-title { font-size:27px; line-height:1.45; margin:8px 0 0; }
.a-body h1 { font-size:21px; margin-top:32px; }
.a-body h2 { font-size:19px; margin-top:34px; border-left:4px solid var(--accent); padding-left:12px; }
.a-body h3 { font-size:16.5px; margin-top:26px; }
.a-body h1:first-child, .a-body h2:first-child { margin-top:0; }
.a-body p { margin:.9em 0; text-align:justify; }

a { color:var(--accent); }
blockquote { margin:1em 0; padding:2px 16px; color:var(--muted); border-left:3px solid var(--line); }
table { border-collapse:collapse; width:100%; margin:1em 0; font-size:14px; }
th,td { border:1px solid var(--line); padding:6px 10px; text-align:left; vertical-align:top; }
th { background:#f3ede2; }
code { background:#f3ede2; padding:1px 5px; border-radius:4px; font-size:.9em; }
pre { background:#f3ede2; padding:12px; border-radius:8px; overflow-x:auto; }
pre code { background:none; padding:0; }
hr { border:none; border-top:1px solid var(--line); margin:2em 0; }

/* ---- home / series ---- */
.hero { text-align:center; padding:34px 10px 6px; }
.hero h1 { font-size:36px; letter-spacing:.12em; margin:0; }
.hero p { color:var(--muted); margin:10px 0 0; font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }
.series { margin-top:30px; }
.series > h2 { border:none; padding:0; font-size:20px; margin:0; }
.series > p.desc { color:var(--muted); margin:4px 0 12px; font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; font-size:14px; }
.cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:10px; }
.cards a { display:block; background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 14px; text-decoration:none; color:var(--ink); font-size:15px; line-height:1.6;
  transition:border-color .15s; }
.cards a:hover { border-color:var(--accent); }
.cards a .t { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
  font-weight:600; line-height:1.6; }
.cards a .excerpt { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;
  color:var(--muted); font-size:13.5px; line-height:1.7; margin-top:6px; }
.heat { color:var(--accent); font-size:12px; font-weight:400; margin-left:6px; white-space:nowrap; }
.count { color:var(--muted); font-size:13px; font-weight:400; font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; }
.g-name { font-size:16px; margin:20px 0 10px; }
.g-name .count { font-size:12.5px; }
.toc-h { font-size:20px; margin:26px 0 4px; padding-bottom:6px; border-bottom:1px solid var(--line); }
.toc-list { list-style:none; margin:0 0 10px; padding:0; columns:2; column-gap:30px; }
.toc-list li { break-inside:avoid; }
.toc-list a { display:block; padding:3px 0; text-decoration:none; color:var(--ink); font-size:14px; line-height:1.6; }
.toc-list a:hover { color:var(--accent); }

/* ---- about box ---- */
.intro { margin-top:28px; background:var(--card); border:1px solid var(--line);
  border-radius:12px; padding:24px 28px; }
.intro p { margin:0; font-size:15.5px; line-height:2; text-align:justify; }
.intro .ov { text-decoration:none; }
.intro .agent-line { margin-top:10px; font-size:14.5px; color:var(--muted); text-align:left; }
.intro .ebook-line { margin-top:12px; font-size:15px; }
.intro .ebook-line a { font-weight:600; }
.intro .ebook-note { color:var(--muted); font-size:13px; }
.socials { display:flex; flex-wrap:wrap; gap:10px 18px; margin-top:16px; padding-top:16px;
  border-top:1px dashed var(--line); }
.socials a, .socials .soc-txt { font-size:13.5px; text-decoration:none; color:var(--muted);
  white-space:nowrap; }
.socials a:hover { color:var(--accent); }

footer.foot { margin-top:44px; padding:14px 0 0; border-top:1px solid var(--line);
  color:var(--muted); font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",sans-serif; font-size:13px; }
footer.foot a { color:var(--muted); }

@media (max-width: 860px) {
  .menu-btn { display:inline-flex; }
  .tagline { display:none; }
  .intro { padding:18px; }
  .searchbox input { width:150px; }
  .layout { gap:0; }
  .sidebar { position:fixed; z-index:90; left:0; top:var(--head-h); bottom:0; width:280px;
    flex:none; background:var(--card); border-right:1px solid var(--line); padding:14px;
    transform:translateX(-102%); transition:transform .2s ease; max-height:none; }
  .sidebar.open { transform:none; box-shadow:0 0 40px rgba(0,0,0,.18); }
  article { padding:24px 22px 30px; }
  .toc-list { columns:1; }
}
/* 暗色仅经手动切换（.dark）生效，站点默认亮色；亮色态声明 only light，
   禁用浏览器（Edge/Chrome 自动深色）对亮色页面的强制压暗 */
:root.light { color-scheme:only light; }
:root.dark { color-scheme:dark; --ink:#d8d2c7; --bg:#221f1a; --card:#2c2822; --accent:#c99b62; --muted:#948c7d; --line:#3d3830; }
:root.dark th, :root.dark code, :root.dark pre { background:#332e27; }
:root.dark .hits { box-shadow:0 8px 28px rgba(0,0,0,.45); }
"""

SEARCH_JS = """(function () {
  var data = null, loading = false;
  var box = document.getElementById('q');
  var hits = document.getElementById('hits');
  var btn = document.getElementById('menuBtn');
  var sidebar = document.getElementById('sidebar');
  var prefix = window.SITE_PREFIX || '';
  var themeBtn = document.getElementById('themeBtn');
  var rootEl = document.documentElement;
  function effTheme() {
    if (rootEl.classList.contains('dark')) return 'dark';
    return 'light'; // 默认亮色：暗色仅手动切换后记忆
  }
  function giscusTheme(t) {
    var f = document.querySelector('iframe.giscus-frame');
    if (!f) return;
    var url = (window.GISCUS_THEMES || {})[t] || t;
    try { f.contentWindow.postMessage({ giscus: { setConfig: { theme: url } } }, 'https://giscus.app'); } catch (e) {}
  }
  function setTheme(t, save) {
    rootEl.classList.toggle('dark', t === 'dark');
    rootEl.classList.toggle('light', t === 'light');
    if (save) { try { localStorage.setItem('theme', t); } catch (e) {} }
    giscusTheme(t);
  }
  var savedTheme = null;
  try { savedTheme = localStorage.getItem('theme'); } catch (e) {}
  if (savedTheme === 'dark' || savedTheme === 'light') {
    setTheme(savedTheme, false);
  }
  var initialTheme = (savedTheme === 'dark' || savedTheme === 'light') ? savedTheme : effTheme();
  giscusTheme(initialTheme);
  setTimeout(function () { giscusTheme(initialTheme); }, 1800);
  // giscus iframe 懒加载：挂载/加载完成时补推当前主题，否则暗色下评论区停在亮色
  new MutationObserver(function () {
    var f = document.querySelector('iframe.giscus-frame');
    if (f && !f.dataset.themeBound) {
      f.dataset.themeBound = '1';
      f.addEventListener('load', function () {
        giscusTheme(effTheme());
        setTimeout(function () { giscusTheme(effTheme()); }, 600);
        setTimeout(function () { giscusTheme(effTheme()); }, 1600);
      });
    }
  }).observe(document.body, { childList: true, subtree: true });
  if (themeBtn) themeBtn.addEventListener('click', function () {
    setTheme(effTheme() === 'dark' ? 'light' : 'dark', true);
  });
  if (btn && sidebar) {
    btn.addEventListener('click', function () { sidebar.classList.toggle('open'); });
  }
  if (!box || !hits) return;

  function ensureData(cb) {
    if (data) return cb();
    if (loading) return setTimeout(function () { ensureData(cb); }, 120);
    loading = true;
    var s = document.createElement('script');
    s.src = prefix + 'search-data.js';
    s.onload = function () { data = window.SEARCH_DATA || []; cb(); };
    s.onerror = function () { loading = false; };
    document.body.appendChild(s);
  }

  box.addEventListener('focus', function () { ensureData(function () {}); });
  box.addEventListener('input', function () {
    ensureData(function () {
      var q = box.value.trim().toLowerCase();
      hits.innerHTML = '';
      if (!q) { hits.classList.remove('show'); return; }
      var n = 0;
      for (var i = 0; i < data.length && n < 30; i++) {
        var d = data[i];
        if (d.t.toLowerCase().indexOf(q) < 0 && d.x.toLowerCase().indexOf(q) < 0) continue;
        var a = document.createElement('a');
        a.href = prefix + d.u;
        var sm = document.createElement('small');
        sm.textContent = d.s;
        a.appendChild(sm);
        a.appendChild(document.createTextNode(d.t));
        hits.appendChild(a);
        n++;
      }
      if (n === 0) {
        var e = document.createElement('a');
        e.textContent = '没有匹配的文章';
        hits.appendChild(e);
      }
      hits.classList.add('show');
    });
  });
  document.addEventListener('click', function (ev) {
    if (ev.target !== box && !hits.contains(ev.target)) hits.classList.remove('show');
  });
})();
"""

ASSET_VER = hashlib.md5((STYLE + SEARCH_JS).encode("utf-8")).hexdigest()[:8]


def clean_output() -> None:
    """Remove generated files but keep .git and README.md."""
    if not OUT.exists():
        OUT.mkdir(parents=True)
        return
    keep = {".git", "README.md", "giscus-light.css", "giscus-dark.css",
            "苏霍壹“马克思+庄子+心理学体系”文集.pdf"}
    for child in OUT.iterdir():
        if child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink()


def main() -> None:
    clean_output()
    md_files = []
    for slug, _, _ in SERIES:
        d = KNOWLEDGE / slug
        if not d.exists():
            continue
        for md_path in sorted(d.glob("*.md")):
            md_files.append((slug, md_path))

    print(f"converting {len(md_files)} articles ...")
    entries = []       # metadata for sidebar/search/cards
    rendered = {}      # (slug, file) -> body html
    search_data = []

    for slug, md_path in md_files:
        md_text = FRONTMATTER.sub("", md_path.read_text(encoding="utf-8"))
        title = article_title(md_path, md_text)
        body_html = strip_leading_h1(pandoc(md_text), title)
        label = dict((s, l) for s, l, _ in SERIES)[slug]
        entries.append({"slug": slug, "label": label, "title": title,
                        "file": md_path.stem, "excerpt": excerpt(md_text)})
        rendered[(slug, md_path.stem)] = body_html
        search_data.append({"t": title, "s": label,
                            "u": quote(slug) + "/" + quote(md_path.stem) + ".html",
                            "x": re.sub(r"\s+", "", md_text)})

    total = len(entries)

    # ---- 综合热度：点赞/评论数来自 giscus 的 GitHub Discussions ----
    heat_map = fetch_heat()
    for e in entries:
        e["heat"] = heat_map.get(f'{e["slug"]}/{e["file"]}', 0)
    build_layout(entries)

    # ---- article pages ----
    for slug, md_path in md_files:
        e = next(x for x in entries if x["slug"] == slug and x["file"] == md_path.stem)
        head = (f'<header class="a-head">'
                f'<div class="a-series"><a href="../{quote(slug)}/index.html">{html.escape(e["label"])}</a></div>'
                f'<h1 class="a-title">{html.escape(e["title"])}</h1></header>')
        body = f'<article>{head}<div class="a-body">{rendered[(slug, md_path.stem)]}</div></article>'
        (OUT / slug).mkdir(parents=True, exist_ok=True)
        (OUT / slug / (md_path.stem + ".html")).write_text(
            render_page(title_tag=f'{e["title"]} · {SITE_TITLE}', body=body,
                        entries=entries, prefix='../',
                        active_series=slug, active_file=e["file"],
                        with_comments=True,
                        canonical=f"{NEW_SITE_BASE}{quote(slug)}/{quote(md_path.stem)}"),
            encoding="utf-8")

    # ---- series index pages ----
    for slug, label, desc in ordered_series():
        groups = series_groups(entries, slug)
        if not groups:
            continue
        total = sum(len(m) for _, m in groups)
        blocks = []
        for glabel, members in groups:
            cards = "\n".join(card_html(e) for e in members)
            blocks.append(f'<h3 class="g-name">{html.escape(glabel)}'
                          f' <span class="count">{len(members)} 篇</span></h3>'
                          f'<div class="cards">{cards}</div>')
        body = (f'<article><header class="a-head">'
                f'<h1 class="a-title">{html.escape(label)} <span class="count">{total} 篇</span></h1>'
                f'</header><p class="desc">{html.escape(desc)}</p>'
                + "\n".join(blocks) + '</article>')
        (OUT / slug).mkdir(parents=True, exist_ok=True)
        (OUT / slug / "index.html").write_text(
            render_page(title_tag=f"{label} · {SITE_TITLE}", body=body,
                        entries=entries, prefix='../', active_series=slug,
                        canonical=f"{NEW_SITE_BASE}{quote(slug)}/"),
            encoding="utf-8")

    # ---- home ----
    sections = []
    for slug, label, desc in ordered_series():
        groups = series_groups(entries, slug)
        if not groups:
            continue
        total = sum(len(m) for _, m in groups)
        blocks = []
        for glabel, members in groups:
            cards = "\n".join(card_html(e) for e in members)
            blocks.append(f'<h3 class="g-name">{html.escape(glabel)}'
                          f' <span class="count">{len(members)} 篇</span></h3>'
                          f'<div class="cards">{cards}</div>')
        sections.append(
            f'<section class="series"><h2>{html.escape(label)}'
            f' <span class="count">{total} 篇</span></h2>'
            f'<p class="desc">{html.escape(desc)}</p>'
            + "\n".join(blocks)
            + f'<p style="margin:10px 0 0"><a class="count" href="{quote(slug)}/index.html">'
              f'系列页 →</a></p></section>')

    # ---- about box + socials (home) ----
    ov = next((e for e in entries if e["file"] == OVERVIEW_ARTICLE), None)
    ov_link = (f'<a class="ov" href="{quote(ov["slug"])}/{quote(ov["file"])}.html">'
               f'→《{ov["title"]}》</a>') if ov else ""
    soc = []
    for icon, name, url in SOCIALS:
        if url:
            soc.append(f'<a href="{html.escape(url, quote=True)}" target="_blank" '
                       f'rel="noopener">{icon} {name}</a>')
        else:
            soc.append(f'<span class="soc-txt">{icon} {name}：苏霍壹</span>')
    about = (f'<section class="intro"><p>{ABOUT_TEXT}{ov_link}</p>'
             f'<p class="ebook-line">📖 <a href="苏霍壹“马克思+庄子+心理学体系”文集.pdf">苏霍壹“马克思+庄子+心理学体系”文集</a>'
             f'<span class="ebook-note">（PDF下载 ·按体系目录编排）</span></p>'
             f'<p class="agent-line">马克思主义主题文集姊妹站：'
             f'<a href="{SISTER_SITE[0]}" target="_blank" rel="noopener">{SISTER_SITE[1]}</a></p>'
             f'<p class="agent-line">欢迎点 github 主页试用我开源的马庄心理学 Agent skill：'
             f'<a href="https://github.com/sukho1/assistant-agent" target="_blank" rel="noopener">'
             f'github.com/sukho1/assistant-agent</a></p>'
             f'<p class="agent-line"><a href="https://justlinknow.com" target="_blank" '
             f'rel="noopener" style="text-decoration:none">justlinknow.com</a>，基于马庄心理学的 AI 心灵对话，及社交功能</p>'
             f'<p class="agent-line"><a href="https://aimap.space" target="_blank" '
             f'rel="noopener" style="text-decoration:none">aimap.space</a>，产业地图（硬科技、AI 产业链、IT 为主）</p>'
             f'<div class="socials">' + "\n".join(soc) + "</div></section>")

    home_body = (f'<div class="hero"><h1>{SITE_TITLE}</h1></div>'
                 + about + "\n".join(sections))
    (OUT / "index.html").write_text(
        render_page(title_tag=SITE_TITLE, body=home_body, entries=entries, prefix='',
                    canonical=NEW_SITE_BASE),
        encoding="utf-8")

    # ---- guestbook ----
    gb_body = (f'<article><header class="a-head"><h1 class="a-title">留言板</h1></header>'
               f'<p class="desc">想说的、想问的、想聊的，都欢迎留在这里。</p></article>')
    (OUT / "guestbook.html").write_text(
        render_page(title_tag=f"留言板 · {SITE_TITLE}", body=gb_body,
                    entries=entries, prefix='', with_comments=True),
        encoding="utf-8")

    # ---- catalog (文章目录) ----
    toc = []
    for slug, label, _ in ordered_series():
        groups = series_groups(entries, slug)
        if not groups:
            continue
        s_total = sum(len(m) for _, m in groups)
        toc.append(f'<h2 class="toc-h">{html.escape(label)}'
                   f' <span class="count">{s_total} 篇</span></h2>')
        for glabel, members in groups:
            toc.append(f'<h3 class="g-name">{html.escape(glabel)}'
                       f' <span class="count">{len(members)} 篇</span></h3>'
                       f'<ul class="toc-list">')
            for e in members:
                toc.append(f'<li><a href="{quote(e["slug"])}/{quote(e["file"])}.html">'
                           f'{html.escape(e["title"])}</a></li>')
            toc.append("</ul>")
    catalog_body = (f'<article><header class="a-head">'
                    f'<h1 class="a-title">文章目录 <span class="count">{len(entries)} 篇</span></h1></header>'
                    f'<p class="desc">全站文章按系列与主题分组，一级为系列，二级为系列内的主题分组，'
                    f'从这里进入任何一篇。</p>'
                    + "\n".join(toc) + '</article>')
    (OUT / "catalog.html").write_text(
        render_page(title_tag=f"文章目录 · {SITE_TITLE}", body=catalog_body,
                    entries=entries, prefix='',
                    canonical=NEW_SITE_BASE),
        encoding="utf-8")

    # ---- assets ----
    (OUT / "style.css").write_text(STYLE, encoding="utf-8")
    (OUT / "search.js").write_text(SEARCH_JS, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    payload = json.dumps(search_data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    (OUT / "search-data.js").write_text(
        "window.SEARCH_DATA=" + payload + ";", encoding="utf-8")

    print(f"done: {len(entries)} articles -> {OUT}")


if __name__ == "__main__":
    main()
