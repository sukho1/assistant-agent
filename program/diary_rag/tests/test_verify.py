"""Tests for diary_rag.verify smoke-result reporting."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_search_smoke_summary_uses_parent_count_and_ranked_slice():
    """A search result reports parent count with the top-ranked slice metadata."""
    from verify import summarize_search_results

    count, top = summarize_search_results(
        {
            "parents": [
                {"date": "2026.9.5", "title": "主要矛盾", "content": "..."},
                {"date": "2026.9.4", "title": "正道不言", "content": "..."},
            ],
                "slices": [
                    {
                        "parent_id": "2026-09-04_0",
                        "date": "2026.9.4",
                        "title": "正道不言",
                    }
                ],
        }
    )

    assert count == 2
    assert top == {"date": "2026.9.4", "title": "正道不言"}


def test_search_smoke_summary_keeps_ranked_slice_after_parent_deduplication():
    """A slice-only response still reports the best matching diary metadata."""
    from verify import summarize_search_results

    count, top = summarize_search_results(
        {
            "parents": [],
            "slices": [{"date": "2026.9.5", "title": "主要矛盾"}],
        }
    )

    assert count == 0
    assert top == {"date": "2026.9.5", "title": "主要矛盾"}


def test_search_smoke_summary_accepts_empty_parent_blocks():
    """A response without parent blocks or slices is reported as empty."""
    from verify import summarize_search_results

    count, top = summarize_search_results({"parents": [], "slices": []})

    assert count == 0
    assert top is None
