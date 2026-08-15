"""L2 segmentation: split parent blocks into child chunks (≤300 chars)."""
import re
import json
import sqlite3
import os
from dataclasses import dataclass, field
from typing import List, Optional

import config


@dataclass
class ChildChunk:
    """One child chunk — the retrieval unit for vector search."""
    id: str
    parent_id: str
    seq: int
    content: str
    sub_title: Optional[str]
    char_count: int


def detect_sub_headings(parent_text: str) -> List[tuple]:
    """Detect sub-headings within a parent block.
    Returns [(start_pos, heading_text), ...]."""
    sub_headings = []

    # Pattern 1: Numbered sub-sections (e.g. "1. xxx", "一、xxx", "（一）xxx")
    for m in re.finditer(r'(?:^|\n)\s*(?:\d+\.|[一-鿿]、|[（(][一-鿿\d]+[）)])[^\n]{2,80}', parent_text):
        sub_headings.append((m.start(), m.group().strip()))

    # Pattern 2: Short lines (2-25 chars) followed by long text, no ending punctuation
    for m in re.finditer(r'(?:^|\n)\s*([^\n]{2,25})\n\s*([^\n]{50,})', parent_text):
        short_line = m.group(1).strip()
        if not re.search(r'[。！？，、；：）\)」』]$', short_line):
            sub_headings.append((m.start(), short_line))

    # Deduplicate by position
    seen = set()
    unique = []
    for pos, text in sub_headings:
        if pos not in seen:
            seen.add(pos)
            unique.append((pos, text))

    return sorted(unique, key=lambda x: x[0])


def split_by_sub_headings(parent_text: str) -> List[str]:
    """Split parent text into segments using detected sub-headings."""
    sub_headings = detect_sub_headings(parent_text)
    if not sub_headings:
        return [parent_text]

    segments = []
    first_pos = sub_headings[0][0]
    if first_pos > 0 and parent_text[:first_pos].strip():
        segments.append(parent_text[:first_pos].strip())

    for i, (pos, heading) in enumerate(sub_headings):
        start = pos
        end = sub_headings[i + 1][0] if i + 1 < len(sub_headings) else len(parent_text)
        segment = parent_text[start:end].strip()
        if segment:
            segments.append(segment)

    return segments


def split_long_segment(segment: str, max_chars: int = config.CHILD_MAX_CHARS) -> List[str]:
    """Split a segment that exceeds max_chars at paragraph boundaries."""
    if len(segment) <= max_chars:
        return [segment]

    chunks = []
    paragraphs = segment.split('\n')
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 1 <= max_chars:
            current = (current + '\n' + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            if len(para) > max_chars:
                sentences = re.split(r'(?<=[。！？])', para)
                sub = ""
                for sent in sentences:
                    if len(sub) + len(sent) <= max_chars:
                        sub += sent
                    else:
                        if sub:
                            chunks.append(sub)
                        sub = sent
                if sub:
                    current = sub
                else:
                    current = ""
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


def create_child_chunks(parent_id: str, parent_text: str, parent_title: Optional[str]) -> List[ChildChunk]:
    """Create child chunks for one parent block.

    Strategy:
    1. Detect sub-headings → split by them
    2. Each sub-heading segment → split at paragraph boundaries to ≤300 chars
    3. Short parents (<500 chars) → single child chunk
    """
    if len(parent_text) <= config.PARENT_MIN_CHARS_FOR_SPLIT:
        return [ChildChunk(
            id=f"{parent_id}_ch0",
            parent_id=parent_id,
            seq=0,
            content=parent_text.strip(),
            sub_title=parent_title,
            char_count=len(parent_text)
        )]

    segments = split_by_sub_headings(parent_text)

    chunks = []
    seq = 0
    for seg in segments:
        sub_title = None
        lines = seg.strip().split('\n')
        first_line = lines[0].strip() if lines else ""
        if len(first_line) <= 30 and first_line:
            sub_title = first_line

        sub_chunks = split_long_segment(seg, config.CHILD_MAX_CHARS)
        for sc in sub_chunks:
            chunks.append(ChildChunk(
                id=f"{parent_id}_ch{seq}",
                parent_id=parent_id,
                seq=seq,
                content=sc.strip(),
                sub_title=sub_title,
                char_count=len(sc)
            ))
            seq += 1

    return chunks


if __name__ == '__main__':
    conn = sqlite3.connect(config.DB_PATH)
    parents = conn.execute("SELECT id, title, content, char_count FROM parents").fetchall()
    conn.close()

    total_chunks = 0
    for pid, ptitle, pcontent, char_count in parents:
        chunks = create_child_chunks(pid, pcontent, ptitle)

        chunk_data = [{
            "id": c.id, "parent_id": c.parent_id, "seq": c.seq,
            "content": c.content, "sub_title": c.sub_title, "char_count": c.char_count
        } for c in chunks]
        os.makedirs(config.CACHE_DIR, exist_ok=True)
        cache_file = os.path.join(config.CACHE_DIR, f"{pid}.l2.json")
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(chunk_data, f, ensure_ascii=False)

        total_chunks += len(chunks)

    print(f"Done. Total child chunks: {total_chunks}")
