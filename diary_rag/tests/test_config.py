"""Tests for diary_rag.config"""
import os
import sys

# Ensure diary_rag is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


def test_config_has_required_attrs():
    """config module exports all required configuration values."""
    import config

    # Paths
    assert os.path.isabs(config.PROJECT_ROOT)
    assert config.DIARY_DIR.endswith('diary')
    assert config.DATA_DIR.endswith('data')
    assert config.DB_PATH.endswith('diary.db')
    assert config.CHROMA_DIR.endswith('chroma')

    # Embedding model
    assert config.EMBED_MODEL_NAME == "BAAI/bge-small-zh-v1.5"
    assert config.EMBED_DIM == 512
    assert config.EMBED_BATCH_SIZE > 0

    # Chunking
    assert config.CHILD_MAX_CHARS == 300
    assert config.PARENT_MIN_CHARS_FOR_SPLIT == 500
    assert config.LONG_PARENT_CHARS == 2000

    # ChromaDB
    assert config.COLLECTION_NAME == "diary_rag"

    # Retrieval
    assert config.DEFAULT_TOP_K == 5
    assert config.OVERSAMPLE_FACTOR == 4


def test_data_dirs_exist_or_creatable():
    """Data directories path are under the expected root."""
    import config

    assert 'diary_rag' in config.DATA_DIR
    assert config.CACHE_DIR.endswith('cache')
    assert config.CHROMA_DIR.endswith('chroma')
    assert config.ARTICLES_DIR.endswith('diary_articles')
