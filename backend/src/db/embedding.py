"""
Embedding service using sentence-transformers (all-MiniLM-L6-v2).
Same model as abra's pgvector implementation — 384 dimensions, runs locally, no API cost.

Singleton pattern: model loads once on first use, reused across requests.
"""

import logging
from typing import List, Union
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model = None


def _get_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
            _model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info(f"Embedding model loaded ({EMBEDDING_DIM} dimensions)")
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
    return _model


def embed_text(text: str) -> List[float]:
    """Embed a single text string. Returns list of floats (384 dim)."""
    model = _get_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Embed multiple texts in batch. More efficient than calling embed_text in a loop."""
    if not texts:
        return []
    model = _get_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64)
    return embeddings.tolist()
