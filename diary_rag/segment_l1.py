"""L1 segmentation: detect signals, split into parent blocks, write to SQLite."""
import re
import json
import sqlite3
import os
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from collections import Counter

from reader import Paragraph, ParagraphStream, read_file
import config


@dataclass
class SignalReport:
    """Auto-detected structural signals in a file."""
    file_name: str
    total_paras: int
    heading_levels: Dict[int, int]
    date_patterns: Dict[str, int]
    inline_day_markers: List[int]
    confidence: float

    @property
    def has_headings(self) -> bool:
        return sum(self.heading_levels.values()) > 0

    @property
    def has_date_patterns(self) -> bool:
        return sum(self.date_patterns.values()) > 0


def detect_signals(stream: ParagraphStream) -> SignalReport:
    """Auto-detect structural signals in a paragraph stream."""
    heading_levels = Counter()
    date_matches = Counter()
    day_markers = []

    date_regexes = [
        (r'^\d{4}\.\d{1,2}\.\d{1,2}', 'YYYY.M.D'),
        (r'^\d{1,2}\.\d{1,2}', 'M.D with title'),
        (r'^\d{1,2}\.\d{1,2}-\d{1,2}\.\d{1,2}', 'M.D-M.D'),
        (r'^\d{4}-\d{2}-\d{2}', 'YYYY-MM-DD'),
        (r'^\d{4}年\d{1,2}月\d{1,2}日', 'YYYY年M月D日'),
    ]

    for p in stream.paragraphs:
        if p.level > 0:
            heading_levels[p.level] += 1

        if p.level == 0 and re.match(r'^\d{1,2}\.\d{1,2}$', p.text.strip()):
            day_markers.append(p.idx)
            date_matches['bare_day_marker'] += 1

        first_30 = p.text.strip()[:30]
        for regex, label in date_regexes:
            if re.search(regex, first_30):
                date_matches[label] += 1

    total = len(stream.paragraphs)
    heading_density = sum(heading_levels.values()) / max(total, 1)
    date_density = sum(date_matches.values()) / max(total, 1)
    confidence = min(1.0, heading_density * 20 + date_density * 10)

    return SignalReport(
        file_name=stream.file_name,
        total_paras=total,
        heading_levels=dict(heading_levels),
        date_patterns=dict(date_matches),
        inline_day_markers=day_markers,
        confidence=confidence
    )


@dataclass
class ParentBlock:
    """One L1 unit: a diary entry, article, memoir segment, or summary."""
    id: str
    date: Optional[str]
    title: Optional[str]
    block_type: str
    char_count: int
    file_src: str
    content: str
    para_start: int
    para_end: int
    confidence: float
    subtopics: List[Dict] = field(default_factory=list)


def _has_week_range(text: str) -> bool:
    return bool(re.match(r'^\d{1,2}\.\d{1,2}-\d{1,2}\.\d{1,2}', text.strip()))


def _has_date_prefix(text: str) -> Optional[str]:
    m = re.match(r'^(\d{4}\.\d{1,2}\.\d{1,2})', text.strip())
    if m: return m.group(1)
    m = re.match(r'^(\d{1,2}\.\d{1,2})', text.strip())
    if m: return m.group(1)
    return None


def _pick_date(text: str) -> Optional[str]:
    for regex in [r'\d{4}\.\d{1,2}\.\d{1,2}', r'\d{4}-\d{2}-\d{2}',
                  r'\d{4}年\d{1,2}月\d{1,2}日']:
        m = re.search(regex, text)
        if m: return m.group(0)
    return None


def _clean_title(text: str) -> str:
    text = re.sub(r'^\d{4}\.\d{1,2}\.\d{1,2}\s*', '', text.strip())
    text = re.sub(r'^\d{1,2}\.\d{1,2}\s*', '', text.strip())
    text = re.sub(r'^\d{1,2}\.\d{1,2}-\d{1,2}\.\d{1,2}\s*', '', text.strip())
    return text.strip()


def _classify_block_type(title: Optional[str], content: str, file_name: str) -> str:
    title_lower = (title or "").lower()
    if any(kw in title_lower for kw in ['总结', '年度', '素描']):
        return 'summary'
    if re.search(r'(论点|论证|结论|核心观点|分析框架)', content[:500]):
        return 'article'
    return 'diary'


def _extract_year_from_filename(filename: str) -> Optional[str]:
    """Extract year from filename like '日记2026H1.docx' or '日记2019.docx'."""
    m = re.search(r'(\d{4})', os.path.basename(filename))
    return m.group(1) if m else None


def _normalize_date(date_str: str, filename: str) -> str:
    """Ensure date has YYYY.M.D format. If M.D only, prepend year from filename."""
    if re.match(r'^\d{4}\.\d{1,2}\.\d{1,2}$', date_str):
        return date_str  # already complete
    if re.match(r'^\d{1,2}\.\d{1,2}$', date_str):
        year = _extract_year_from_filename(filename)
        if year:
            return f"{year}.{date_str}"
    return date_str


def heuristic_split(stream: ParagraphStream, signals: SignalReport) -> List[ParentBlock]:
    """Rule-based L1 split using detected signals."""
    blocks = []
    paras = stream.paragraphs
    total = len(paras)

    if total == 0:
        return blocks

    i = 0
    block_idx = 0
    current_week_date = None
    last_known_date = None  # for inheriting date to consecutive undated entries

    while i < total:
        p = paras[i]

        is_boundary = False
        block_date = None
        block_title = None
        confidence = signals.confidence

        if p.level >= 2:
            date_str = _has_date_prefix(p.text)
            if date_str:
                is_boundary = True
                block_date = date_str
                block_title = _clean_title(p.text)
                confidence = 0.95
            elif _has_week_range(p.text):
                is_boundary = True
                block_date = _pick_date(p.text)
                block_title = _clean_title(p.text)
                current_week_date = block_date
                confidence = 0.90
            elif re.match(r'^(文章合集|总结|素描|酝酿)$', p.text.strip()):
                i += 1
                continue
            else:
                is_boundary = True
                block_title = p.text.strip()
                block_date = current_week_date
                confidence = 0.60

        elif signals.inline_day_markers and p.idx in signals.inline_day_markers:
            is_boundary = True
            block_date = p.text.strip()
            block_title = None
            confidence = 0.85

        if is_boundary:
            content_start = i
            content_text = p.text
            j = i + 1
            while j < total:
                next_p = paras[j]
                next_is_boundary = False
                if next_p.level >= 2:
                    next_is_boundary = True
                elif signals.inline_day_markers and next_p.idx in signals.inline_day_markers:
                    next_is_boundary = True

                if next_is_boundary:
                    break
                content_text += "\n" + next_p.text
                j += 1

            # Skip structural heading dividers: no date + very short (<50 chars)
            if not block_date and len(content_text.strip()) < 50:
                i = j
                continue

            block_type = _classify_block_type(block_title, content_text, stream.file_name)
            block_date = _normalize_date(block_date, stream.file_name) if block_date else None
            # Inherit date from the last known dated entry for same-day continuation blocks
            if not block_date and last_known_date:
                block_date = last_known_date
            if block_date:
                last_known_date = block_date
            date_slug = block_date.replace('.', '-') if block_date else 'nodate'
            block_id = f"{date_slug}_{block_type}_{block_idx}"

            blocks.append(ParentBlock(
                id=block_id,
                date=block_date,
                title=block_title,
                block_type=block_type,
                char_count=len(content_text),
                file_src=stream.file_name,
                content=content_text,
                para_start=content_start,
                para_end=j - 1,
                confidence=confidence,
            ))
            block_idx += 1
            i = j
        else:
            i += 1

    return blocks


def init_db():
    """Create SQLite database and parents table."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parents (
            id TEXT PRIMARY KEY,
            date TEXT,
            title TEXT,
            block_type TEXT,
            char_count INTEGER,
            file_src TEXT,
            content TEXT,
            confidence REAL,
            para_start INTEGER,
            para_end INTEGER
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_parents_date ON parents(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_parents_type ON parents(block_type)")
    conn.commit()
    return conn


def save_parents(conn, blocks: List[ParentBlock]):
    """Insert or replace parent blocks into SQLite."""
    conn.executemany("""
        INSERT OR REPLACE INTO parents (id, date, title, block_type, char_count, file_src, content, confidence, para_start, para_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [(b.id, b.date, b.title, b.block_type, b.char_count, b.file_src, b.content, b.confidence, b.para_start, b.para_end) for b in blocks])
    conn.commit()


def hash_file(file_path: str) -> str:
    """SHA256 of file content for cache key."""
    h = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()[:16]


def process_file(file_path: str, conn, force: bool = False) -> int:
    """Process one diary file: read -> detect -> split -> save. Returns block count."""
    fname = os.path.basename(file_path)

    cache_file = os.path.join(config.CACHE_DIR, f"{fname}.l1.json")
    if not force and os.path.exists(cache_file):
        with open(cache_file, 'r', encoding='utf-8') as f:
            blocks_data = json.load(f)
        blocks = [ParentBlock(**b) for b in blocks_data]
        save_parents(conn, blocks)
        print(f"  [CACHE] {fname}: {len(blocks)} blocks")
        return len(blocks)

    print(f"  [PROCESS] {fname}...")
    try:
        stream = read_file(file_path)
    except Exception as e:
        print(f"  [ERROR] {fname}: {e}")
        return 0

    signals = detect_signals(stream)
    print(f"    confidence={signals.confidence:.2f}, headings={dict(signals.heading_levels)}, dates={dict(signals.date_patterns)}")

    blocks = heuristic_split(stream, signals)
    print(f"    → {len(blocks)} blocks")

    save_parents(conn, blocks)

    os.makedirs(config.CACHE_DIR, exist_ok=True)
    block_dicts = [{k: v for k, v in b.__dict__.items() if k != 'subtopics'} for b in blocks]
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(block_dicts, f, ensure_ascii=False, indent=2)

    return len(blocks)


if __name__ == '__main__':
    conn = init_db()
    files = sorted(
        f for f in (os.path.join(config.DIARY_DIR, fn) for fn in os.listdir(config.DIARY_DIR))
        if f.endswith('.docx')
    )
    total = 0
    for fp in files:
        n = process_file(fp, conn)
        total += n
    conn.close()
    print(f"\nDone. Total parent blocks: {total}")
