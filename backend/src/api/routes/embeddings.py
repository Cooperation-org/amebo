"""
Embeddings route — text embedding and similarity via sentence-transformers.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.db.embedding import embed_text, embed_texts

router = APIRouter()
logger = logging.getLogger(__name__)


class SimilarityRequest(BaseModel):
    reference: str = Field(..., description="Reference text to compare against")
    texts: List[str] = Field(..., description="Texts to compare with the reference")


class SimilarityScore(BaseModel):
    text: str
    score: float  # 0.0 to 1.0 (cosine similarity)


class SimilarityResponse(BaseModel):
    reference: str
    scores: List[SimilarityScore]
    overall: float  # average of all scores, 0.0 to 1.0


@router.post("/similarity", response_model=SimilarityResponse)
async def compute_similarity(req: SimilarityRequest):
    """
    Compute cosine similarity between a reference text and a list of texts.

    Uses sentence-transformers/all-MiniLM-L6-v2 (384-dim, normalized embeddings).
    For normalized vectors, cosine similarity = dot product.
    """
    if not req.reference.strip():
        raise HTTPException(status_code=400, detail="reference cannot be empty")

    if not req.texts:
        raise HTTPException(status_code=400, detail="texts cannot be empty")

    try:
        # Embed reference
        ref_embedding = embed_text(req.reference)

        # Embed all texts to compare
        texts_to_embed = [t for t in req.texts if t.strip()]
        if not texts_to_embed:
            raise HTTPException(status_code=400, detail="No valid texts to compare")

        text_embeddings = embed_texts(texts_to_embed)

        # Compute cosine similarity: dot product of normalized vectors
        scores: List[SimilarityScore] = []
        for i, embedding in enumerate(text_embeddings):
            # Dot product (since embeddings are L2-normalized)
            similarity = sum(r * e for r, e in zip(ref_embedding, embedding))
            # Clamp to [0, 1] in case of floating point drift
            similarity = max(0.0, min(1.0, similarity))
            scores.append(SimilarityScore(text=texts_to_embed[i], score=round(similarity, 4)))

        overall = sum(s.score for s in scores) / len(scores) if scores else 0.0

        logger.debug(f"Similarity: overall={overall:.4f}, {len(scores)} texts")

        return SimilarityResponse(
            reference=req.reference,
            scores=scores,
            overall=round(overall, 4),
        )
    except Exception as e:
        logger.error(f"Similarity computation failed: {e}")
        raise HTTPException(status_code=500, detail="Embedding computation failed")
