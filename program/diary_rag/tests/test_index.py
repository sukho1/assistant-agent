"""Tests for diary_rag.index — RED phase."""
import os
import sys
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_temp_cache_file(chunks, suffix=".l2.json"):
    """Create a temp l2.json cache file, return (path, cleanup_fn)."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode='w', encoding='utf-8')
    json.dump(chunks, tmp, ensure_ascii=False)
    tmp.close()
    return tmp.name


class TestLoadChildChunks:

    def test_loads_l2_cache_files(self):
        """Loads all .l2.json files from cache directory."""
        from index import load_child_chunks
        import config

        original_cache = config.CACHE_DIR
        tmp_cache = tempfile.mkdtemp()
        config.CACHE_DIR = tmp_cache

        try:
            sample = [{
                "id": "test_ch0",
                "parent_id": "test_parent",
                "seq": 0,
                "content": "Test content.",
                "sub_title": None,
                "char_count": 13
            }]
            fp = _make_temp_cache_file(sample)
            os.rename(fp, os.path.join(tmp_cache, "test.l2.json"))

            chunks = load_child_chunks()
            assert len(chunks) == 1
            assert chunks[0]["id"] == "test_ch0"
            assert chunks[0]["parent_id"] == "test_parent"
        finally:
            config.CACHE_DIR = original_cache
            import shutil
            shutil.rmtree(tmp_cache, ignore_errors=True)

    def test_returns_empty_for_no_cache(self):
        """Returns empty list when no cache files exist."""
        from index import load_child_chunks
        import config

        original_cache = config.CACHE_DIR
        tmp_cache = tempfile.mkdtemp()
        config.CACHE_DIR = tmp_cache

        try:
            chunks = load_child_chunks()
            assert chunks == []
        finally:
            config.CACHE_DIR = original_cache
            import shutil
            shutil.rmtree(tmp_cache, ignore_errors=True)


if __name__ == '__main__':
    suite = TestLoadChildChunks()
    passed = 0
    failed = 0
    for name in dir(suite):
        if name.startswith('test_'):
            fn = getattr(suite, name)
            try:
                fn()
                print(f"  PASS {name}")
                passed += 1
            except ModuleNotFoundError as e:
                print(f"  FAIL {name}: module not found - {e}")
                failed += 1
            except Exception as e:
                print(f"  FAIL {name}: {e}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    if failed > 0:
        print("RED")
