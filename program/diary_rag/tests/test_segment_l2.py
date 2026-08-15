"""Tests for diary_rag.segment_l2 — RED phase."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSubHeadingDetection:
    """RED: detect_sub_headings tests."""

    def test_numbered_sub_headings(self):
        """Detect numbered sub-headings like '1. xxx', '一、xxx'."""
        from segment_l2 import detect_sub_headings

        text = """前言介绍
1. AI时代的挑战
这里有很多内容需要讨论...
2. 马克思的回应
关于异化的分析...
（一）具体案例
某公司的实践...
"""

        headings = detect_sub_headings(text)
        titles = [h[1] for h in headings]
        assert any('AI时代' in t for t in titles), f"Should find '1. AI时代的挑战', got {titles}"
        assert any('马克思' in t for t in titles), f"Should find '2. 马克思的回应', got {titles}"

    def test_short_line_sub_heading(self):
        """Short lines followed by long text are sub-headings."""
        from segment_l2 import detect_sub_headings

        text = """活在当下
这是一个非常重要的话题，涉及时间感知和存在的本质我们需要从多个角度来看这个问题涉及到生活的方方面面不能简单回答。这篇文章将详细展开论述继续补充更多内容。
"""

        headings = detect_sub_headings(text)
        titles = [h[1] for h in headings]
        assert any('活在当下' in t for t in titles), f"Should find '活在当下', got {titles}"

    def test_no_sub_headings_in_plain_text(self):
        """Plain text without sub-headings returns empty list."""
        from segment_l2 import detect_sub_headings

        text = "今天早上起来，天气很好。出门散了步。回家做了饭。"
        headings = detect_sub_headings(text)
        assert len(headings) == 0, f"Expected 0 headings, got {headings}"


class TestSplitBySubHeadings:
    """RED: split_by_sub_headings tests."""

    def test_splits_into_segments(self):
        """Text with sub-headings splits into multiple segments."""
        from segment_l2 import split_by_sub_headings

        text = """前言

1. 第一部分
这是第一部分的内容。

2. 第二部分
这是第二部分的内容。"""

        segments = split_by_sub_headings(text)
        assert len(segments) >= 2, f"Expected >=2 segments, got {len(segments)}"


class TestChunkSizeLimits:
    """RED: child chunks respect max char limit."""

    def test_short_parent_single_chunk(self):
        """Parent <500 chars becomes single child chunk."""
        from segment_l2 import create_child_chunks

        text = "今天天气很好。"
        chunks = create_child_chunks("test_id", text, None)
        assert len(chunks) == 1
        assert chunks[0].parent_id == "test_id"
        assert chunks[0].content == text.strip()

    def test_split_long_paragraph(self):
        """Paragraph exceeding max chars splits at sentence boundaries."""
        from segment_l2 import split_long_segment

        long_text = "第一句话。第二句话。" * 50  # ~600 chars
        assert len(long_text) > 300

        chunks = split_long_segment(long_text, 300)
        for chunk in chunks:
            assert len(chunk) <= 310, f"Chunk too long: {len(chunk)} chars"

    def test_all_chunks_have_parent_id(self):
        """Every child chunk references its parent."""
        from segment_l2 import create_child_chunks

        text = "段落一。\n段落二。\n段落三。\n段落四。" * 10
        chunks = create_child_chunks("parent_001", text, "Test Title")
        for chunk in chunks:
            assert chunk.parent_id == "parent_001"
            assert chunk.id.startswith("parent_001_ch")
            assert chunk.char_count == len(chunk.content)


if __name__ == '__main__':
    suites = [
        TestSubHeadingDetection(),
        TestSplitBySubHeadings(),
        TestChunkSizeLimits(),
    ]
    passed = 0
    failed = 0
    for suite in suites:
        for name in dir(suite):
            if name.startswith('test_'):
                fn = getattr(suite, name)
                try:
                    fn()
                    print(f"  PASS {name}")
                    passed += 1
                except ModuleNotFoundError as e:
                    print(f"  FAIL {name}: module not found (expected RED) - {e}")
                    failed += 1
                except Exception as e:
                    print(f"  FAIL {name}: {e}")
                    failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed > 0:
        print("RED - expected: segment_l2.py doesn't exist yet")
