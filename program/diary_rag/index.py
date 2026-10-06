"""Chunk layer: load L2 child chunks from cache — the input to embed_all."""
import json
import os
import glob
from typing import List

import config


def load_child_chunks() -> List[dict]:
    """Load all L2 child chunks from cache."""
    all_chunks = []
    pattern = os.path.join(config.CACHE_DIR, "*.l2.json")
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath, 'r', encoding='utf-8') as f:
            chunks = json.load(f)
            all_chunks.extend(chunks)
    return all_chunks
