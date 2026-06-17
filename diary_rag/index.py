"""Index layer: load child chunks, encode, store in ChromaDB."""
import json
import os
import glob
from typing import List

import chromadb
from sentence_transformers import SentenceTransformer

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


def build_index(model: SentenceTransformer, chunks: List[dict], collection):
    """Encode chunks in batches and store in ChromaDB."""
    batch_size = config.EMBED_BATCH_SIZE
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        texts = [c["content"] for c in batch]
        ids = [c["id"] for c in batch]

        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=batch_size
        )

        metadatas = [{
            "parent_id": c["parent_id"],
            "sub_title": c.get("sub_title", "") or "",
            "char_count": c["char_count"]
        } for c in batch]

        collection.add(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=texts,
            metadatas=metadatas
        )

        print(f"  Indexed {min(i + batch_size, len(chunks))}/{len(chunks)}")


if __name__ == '__main__':
    print(f"Loading model: {config.EMBED_MODEL_NAME}...")
    model = SentenceTransformer(config.EMBED_MODEL_NAME, local_files_only=True)

    print("  Warming up...")
    model.encode(["预热"], normalize_embeddings=True, show_progress_bar=False)

    print("Loading child chunks...")
    chunks = load_child_chunks()
    print(f"  {len(chunks)} chunks to index")

    client = chromadb.PersistentClient(path=config.CHROMA_DIR)
    try:
        client.delete_collection(config.COLLECTION_NAME)
        print(f"  Deleted existing collection '{config.COLLECTION_NAME}'")
    except Exception:
        pass
    collection = client.create_collection(
        name=config.COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )

    print("Indexing...")
    build_index(model, chunks, collection)
    print(f"Done. Collection '{config.COLLECTION_NAME}': {collection.count()} items")
