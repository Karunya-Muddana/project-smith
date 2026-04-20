"""
Embedding backend for Smith memory.

Primary:  sentence-transformers all-MiniLM-L6-v2 (~22 MB, 384 dims, CPU-only ~5 ms/query)
Fallback: Hash-based pseudo-embedder — zero extra dependencies, lower accuracy.
"""

from __future__ import annotations

import hashlib
import logging
from typing import List, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

logger = logging.getLogger("smith.memory.embedder")

# Silence noisy third-party loggers from sentence-transformers / HuggingFace
for _noisy in ("sentence_transformers", "transformers", "httpx", "huggingface_hub",
               "filelock", "torch", "tqdm"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

DIM = 384


class BaseEmbedder:
    def embed(self, text: str) -> np.ndarray:
        raise NotImplementedError

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return np.stack([self.embed(t) for t in texts])


class SentenceTransformerEmbedder(BaseEmbedder):
    """Uses all-MiniLM-L6-v2 via sentence-transformers (downloaded once to HF cache)."""

    def __init__(self):
        import os
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer("all-MiniLM-L6-v2", show_progress_bar=False)
        logger.debug("SentenceTransformerEmbedder loaded (all-MiniLM-L6-v2)")

    def embed(self, text: str) -> np.ndarray:
        vec = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.astype(np.float32)

    def embed_batch(self, texts: List[str]) -> np.ndarray:
        vecs = self._model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return vecs.astype(np.float32)


class HashEmbedder(BaseEmbedder):
    """
    Fallback when sentence-transformers is unavailable.
    Produces a 384-dim vector from character bigram hashes — no torch required.
    Semantics are weak but consistent (same text always maps to same vector).
    """

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(DIM, dtype=np.float32)
        text = text.lower()
        # Character bigrams
        tokens = [text[i : i + 2] for i in range(len(text) - 1)] or [text[:1] or "?"]
        for tok in tokens:
            digest = hashlib.sha256(tok.encode()).digest()
            bucket = int.from_bytes(digest[:2], "big") % DIM
            # Use next two bytes as a small float contribution
            val = int.from_bytes(digest[2:4], "big") / 65535.0
            vec[bucket] += val
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec


# Module-level singleton
_embedder_instance: BaseEmbedder | None = None


def get_embedder() -> BaseEmbedder:
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance
    try:
        _embedder_instance = SentenceTransformerEmbedder()
    except ImportError:
        logger.warning(
            "sentence-transformers not installed — using hash embedder (reduced accuracy). "
            "Run: pip install sentence-transformers"
        )
        _embedder_instance = HashEmbedder()
    return _embedder_instance
