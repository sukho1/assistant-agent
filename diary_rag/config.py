"""diary_rag configuration — paths, model, chunk parameters."""
import os

# Paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIARY_DIR = os.path.join(PROJECT_ROOT, "diary")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")
DB_PATH = os.path.join(DATA_DIR, "diary.db")
ARTICLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "diary_articles")

# Embedding model
EMBED_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
EMBED_DIM = 512
EMBED_BATCH_SIZE = 32
EMBED_MAX_TOKENS = 512

# Chunking
CHILD_MAX_CHARS = 300
PARENT_MIN_CHARS_FOR_SPLIT = 500
LONG_PARENT_CHARS = 2000

# ChromaDB
COLLECTION_NAME = "diary_rag"

# Retrieval
DEFAULT_TOP_K = 5
OVERSAMPLE_FACTOR = 4

# LLM fallback (optional — segment_l1/l2 use if configured)
LLM_API_URL = os.environ.get("DIARY_RAG_LLM_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_API_KEY = os.environ.get("DIARY_RAG_LLM_KEY", "")
LLM_MODEL = os.environ.get("DIARY_RAG_LLM_MODEL", "deepseek-chat")
