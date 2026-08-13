"""Tests for diary_rag.segment_l1 — TDD RED phase."""
import os
import sys
import tempfile
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reader import Paragraph, ParagraphStream


def _make_stream(paragraphs_data):
    """Create a ParagraphStream from list of (style, text) tuples."""
    paras = []
    for i, (style, text) in enumerate(paragraphs_data):
        level = 0
        import re
        m = re.match(r'^Heading\s+(\d+)$', style, re.IGNORECASE)
        if m:
            level = int(m.group(1))
        paras.append(Paragraph(idx=i, style=style, level=level, text=text, char_count=len(text)))
    return ParagraphStream(file_path="/test/diary.docx", file_name="diary.docx", paragraphs=paras)


class TestSignalDetection:
    """RED: signal detection tests."""

    def test_detect_diary_with_headings_and_dates(self):
        """File with Heading 3 entries + bare day markers gets high confidence."""
        from segment_l1 import detect_signals

        stream = _make_stream([
            ("Normal", "Some preamble."),
            ("Heading 3", "1.1-1.4 Week one"),
            ("Normal", "1.1"),
            ("Normal", "Today I went for a walk."),
            ("Normal", "1.2"),
            ("Normal", "Wrote an article about Marx."),
            ("Heading 3", "1.5 Article on AI"),
            ("Normal", "Discussed AI and society."),
        ])

        signals = detect_signals(stream)
        assert signals.total_paras == 8
        assert signals.heading_levels.get(3) == 2, "Should detect 2 Heading 3 entries"
        assert signals.date_patterns.get('M.D-M.D') >= 1, "Should detect M.D-M.D pattern"
        assert len(signals.inline_day_markers) >= 2, "Should detect 1.1 and 1.2 as day markers"
        assert signals.confidence > 0.5, f"Confidence should be >0.5, got {signals.confidence}"

    def test_detect_memoir_low_confidence(self):
        """File with no headings and no date patterns gets low confidence."""
        from segment_l1 import detect_signals

        stream = _make_stream([
            ("Normal", "My childhood was filled with flowers."),
            ("Normal", "The courtyard where I grew up..."),
            ("Normal", "We played every afternoon."),
        ])

        signals = detect_signals(stream)
        assert signals.total_paras == 3
        assert signals.has_headings is False
        assert signals.has_date_patterns is False
        assert signals.confidence < 0.3, f"Low-structure file should have low confidence, got {signals.confidence}"

    def test_detect_year_month_date_pattern(self):
        """File with YYYY.M.D date patterns."""
        from segment_l1 import detect_signals

        stream = _make_stream([
            ("Heading 2", "2013.1.7 US business trip"),
            ("Normal", "Met with clients in New York."),
            ("Heading 2", "2013.2.15 Product launch"),
            ("Normal", "Launched the new platform."),
        ])

        signals = detect_signals(stream)
        assert signals.date_patterns.get('YYYY.M.D', 0) >= 2
        assert signals.confidence > 0.7


class TestHeuristicSplit:
    """RED: heuristic L1 split tests."""

    def test_split_diary_entries(self):
        """Diary entries with dates are correctly separated."""
        from segment_l1 import detect_signals, heuristic_split

        stream = _make_stream([
            ("Heading 3", "1.1 Walk"),
            ("Normal", "Walked by the river."),
            ("Normal", "1.2"),
            ("Normal", "Wrote an article."),
            ("Heading 3", "1.5 Meeting"),
            ("Normal", "Team meeting at 3pm."),
        ])

        signals = detect_signals(stream)
        blocks = heuristic_split(stream, signals)

        assert len(blocks) >= 3, f"Expected >=3 blocks, got {len(blocks)}"
        # First block: Heading 3 "1.1 Walk"
        assert blocks[0].title == "Walk"
        assert blocks[0].date == "1.1"
        # Second block: inline day marker "1.2"
        day_blocks = [b for b in blocks if b.date == "1.2"]
        assert len(day_blocks) == 1
        assert "Wrote an article" in day_blocks[0].content

    def test_block_type_classification(self):
        """Blocks get reasonable type classifications."""
        from segment_l1 import detect_signals, heuristic_split

        stream = _make_stream([
            ("Heading 3", "1.1 Daily note"),
            ("Normal", "Short entry."),
            ("Heading 3", "2026年工作总结"),
            ("Normal", "This year I achieved many things..."),
            ("Normal", "论点：所有问题都是社会问题..."),
        ])

        signals = detect_signals(stream)
        blocks = heuristic_split(stream, signals)

        types = {b.block_type for b in blocks}
        # Short entry should be diary
        diary = [b for b in blocks if "Daily" in (b.title or "")]
        assert diary, "Should have a diary block"
        assert diary[0].block_type == 'diary'

    def test_blocks_have_content(self):
        """All blocks contain their paragraph text."""
        from segment_l1 import detect_signals, heuristic_split

        stream = _make_stream([
            ("Heading 3", "1.1 Test"),
            ("Normal", "Content line one."),
            ("Normal", "Content line two."),
            ("Heading 3", "1.2 Test 2"),
            ("Normal", "More content."),
        ])

        signals = detect_signals(stream)
        blocks = heuristic_split(stream, signals)

        for block in blocks:
            assert len(block.content) > 0, f"Block '{block.title}' has empty content"
            assert block.char_count == len(block.content)
            assert block.file_src == "diary.docx"


class TestSQLiteStorage:
    """RED: SQLite parent block storage tests."""

    def test_init_db_creates_table(self):
        """init_db creates the parents table."""
        from segment_l1 import init_db
        import config

        # Use temp DB for test
        original_db = config.DB_PATH
        tmp_db = tempfile.mktemp(suffix='.db')
        config.DB_PATH = tmp_db

        try:
            conn = init_db()
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = [t[0] for t in tables]
            assert 'parents' in table_names, f"Expected 'parents' table, got {table_names}"
            conn.close()
        finally:
            config.DB_PATH = original_db
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)

    def test_save_parents_inserts(self):
        """save_parents inserts blocks that can be read back."""
        from segment_l1 import init_db, save_parents, ParentBlock
        import config

        original_db = config.DB_PATH
        tmp_db = tempfile.mktemp(suffix='.db')
        config.DB_PATH = tmp_db

        try:
            conn = init_db()
            blocks = [
                ParentBlock(
                    id="2026-01-05_diary_0",
                    date="2026.1.5",
                    title="Test Entry",
                    block_type="diary",
                    char_count=100,
                    file_src="test.docx",
                    content="Full content here.",
                    para_start=0,
                    para_end=2,
                    confidence=0.95,
                )
            ]
            save_parents(conn, blocks)

            rows = conn.execute("SELECT * FROM parents WHERE id=?", (blocks[0].id,)).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == "2026.1.5"  # date
            assert rows[0][2] == "Test Entry"  # title
            assert rows[0][3] == "diary"       # block_type
            assert rows[0][6] == "Full content here."  # content
            conn.close()
        finally:
            config.DB_PATH = original_db
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)


class TestDateNormalization:
    """RED: _normalize_date should fill year from filename."""

    def test_normalize_keeps_full_date(self):
        from segment_l1 import _normalize_date
        assert _normalize_date("2026.1.5", "日记2026H1.docx") == "2026.1.5"

    def test_normalize_adds_year_from_h1(self):
        from segment_l1 import _normalize_date
        assert _normalize_date("1.5", "日记2026H1.docx") == "2026.1.5"

    def test_normalize_adds_year_from_full_year(self):
        from segment_l1 import _normalize_date
        assert _normalize_date("8.15", "日记2019.docx") == "2019.8.15"

    def test_normalize_adds_year_from_h2(self):
        from segment_l1 import _normalize_date
        assert _normalize_date("11.23", "日记2025H2.docx") == "2025.11.23"


class TestDateQuality:
    """E2E: Every parent block from real diary files has a valid date."""

    def test_no_nodate_in_dated_files(self):
        """Files with years in the filename should produce dated entries."""
        from segment_l1 import process_file, init_db
        import config
        import tempfile
        import glob

        original_db = config.DB_PATH
        tmp_db = tempfile.mktemp(suffix='.db')
        config.DB_PATH = tmp_db

        try:
            conn = init_db()

            # Test a few files that definitely have dates
            test_files = ['日记2026H1.docx', '日记2017.docx', '日记2019.docx']
            for fname in test_files:
                fpath = config.DIARY_DIR + '/' + fname
                if os.path.exists(fpath):
                    process_file(fpath, conn, force=True)

            # Check: no entry should be "nodate" for dated files
            nodate_count = conn.execute(
                "SELECT COUNT(*) FROM parents WHERE id LIKE 'nodate%' AND file_src NOT LIKE '1989%' AND file_src NOT LIKE '2003%'"
            ).fetchone()[0]
            assert nodate_count == 0, f"Found {nodate_count} nodate entries in dated files"

            # Check: all entries from 2013+ files have YYYY.M.D format dates
            bad_dates = conn.execute(
                "SELECT id, date, title, file_src FROM parents WHERE date IS NOT NULL AND date NOT GLOB '20[0-9][0-9].*' AND file_src LIKE '日记20%' LIMIT 5"
            ).fetchall()
            assert len(bad_dates) == 0, f"Found {len(bad_dates)} entries without year in date"

            conn.close()
        finally:
            config.DB_PATH = original_db
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)


if __name__ == '__main__':
    suites = [
        TestSignalDetection(),
        TestHeuristicSplit(),
        TestSQLiteStorage(),
        TestDateNormalization(),
        TestDateQuality(),
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
        print("RED - expected: segment_l1.py doesn't exist yet")
