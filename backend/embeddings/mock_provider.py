"""Deterministic Mock Embedding Provider for offline tests, sandboxes, and CI/CD.

Generates 384-dimensional dense float vectors using semantic n-gram and intent hashing.
Provides realistic cosine similarity scores for English, Hindi, and Hinglish intent
testing without requiring PyTorch or 470MB model downloads.
"""

import hashlib
import math
import re
from typing import List

from backend.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """384-dimensional deterministic semantic-hash provider."""

    def __init__(self, model_name: str = "mock-multilingual-384"):
        self._model_name = model_name
        self._dimension = 384

        # Semantic concept clusters mapped to dedicated embedding subspaces
        self._semantic_concepts = {
            "schedule": [
                "stream", "live", "start", "time", "when", "kab", "shuru", "timing",
                "schedule", "broadcast", "aaj", "baje", "स्ट्रीम", "कब", "शुरू"
            ],
            "camera": [
                "camera", "cam", "lens", "gear", "dslr", "aperture", "zv-e10", "sony", "canon",
                "कैमरा", "इस्तेमाल"
            ],
            "mic": [
                "mic", "microphone", "audio", "sound", "volume", "voice", "awaz", "shor", "setup",
                "माइक"
            ],
            "price": [
                "price", "cost", "how much", "rate", "kitna", "kitne", "daam", "rupee", "rs", "buy", "pada",
                "दाम", "कितना"
            ],
            "location": [
                "where", "city", "place", "kahan", "rehte", "live", "country", "stay", "platform", "hosting",
                "कहाँ"
            ],
            "pc_specs": [
                "pc", "specs", "gpu", "graphics", "cpu", "ram", "rtx", "processor", "hardware", "computer"
            ],
            "gaming": [
                "game", "gaming", "play", "playing", "gta", "title", "गेम"
            ],
            "negation": [
                "nahi", "not", "no", "never", "mat", "problem", "issue", "kharab", "broken", "freeze", "lag",
                "नहीं", "खराब"
            ],
            "greeting": [
                "hi", "hello", "hey", "namaste", "sup", "bhai", "bro", "sir"
            ],
        }

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _text_to_semantic_vector(self, text: str) -> List[float]:
        vec = [0.0] * self._dimension
        norm = str(text).lower().strip()
        # Clean punctuation except alphanumeric, unicode words
        tokens = set(re.findall(r"[\w\u0900-\u097F]+", norm))

        # Subspace 0 - 179: Concept activation signals
        chunk_size = 20
        concept_keys = list(self._semantic_concepts.keys())
        for idx, concept in enumerate(concept_keys):
            words = set(self._semantic_concepts[concept])
            overlap = len(tokens & words)
            if overlap > 0:
                base_idx = idx * chunk_size
                val = 2.0 + (overlap * 0.8)
                for i in range(chunk_size):
                    h = hashlib.sha256(f"{concept}_{i}".encode("utf-8")).digest()[0] / 255.0
                    vec[base_idx + i] += val * h

        # Subspace 180 - 383: General character n-gram fingerprint
        ngram_space = self._dimension - 180
        clean_chars = re.sub(r"\s+", " ", norm)
        for i in range(len(clean_chars) - 2):
            trigram = clean_chars[i : i + 3]
            h = int(hashlib.md5(trigram.encode("utf-8")).hexdigest()[:8], 16)
            pos = 180 + (h % ngram_space)
            vec[pos] += 1.0

        # L2-normalize
        norm_val = math.sqrt(sum(x * x for x in vec))
        if norm_val > 1e-9:
            return [x / norm_val for x in vec]
        vec[0] = 1.0
        return vec

    def embed_text(self, text: str) -> List[float]:
        return self._text_to_semantic_vector(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._text_to_semantic_vector(t) for t in texts]
