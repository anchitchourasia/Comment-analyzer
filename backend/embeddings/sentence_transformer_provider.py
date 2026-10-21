"""SentenceTransformer embedding provider using HuggingFace / PyTorch models.

Default model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
Dimension: 384
Supports: English, Hindi script (Devanagari), and Romanized Hinglish.
"""

import os
from pathlib import Path
from typing import List, Optional

from backend.embeddings.base import BaseEmbeddingProvider


class SentenceTransformerEmbeddingProvider(BaseEmbeddingProvider):
    """Local SentenceTransformer provider with configurable cache and lazy loading."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_dir: Optional[str] = None,
    ):
        self._model_name = model_name
        self._dimension = 384
        self._model = None
        self._load_error = None

        # Resolve cache dir safely across Linux and Windows
        env_cache = os.environ.get("SEMANTIC_MODEL_CACHE_DIR")
        chosen_cache = cache_dir or env_cache
        if chosen_cache:
            try:
                # Sanitize potential Windows path when running on POSIX
                self._cache_dir = str(Path(chosen_cache).expanduser())
            except Exception:
                self._cache_dir = None
        else:
            self._cache_dir = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_available(self) -> bool:
        """Check if model can be initialized."""
        try:
            self._ensure_loaded()
            return self._model is not None
        except Exception:
            return False

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def _ensure_loaded(self):
        """Lazy loader for the model to prevent startup penalties."""
        if self._model is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(f"SentenceTransformer load failed previously: {self._load_error}")

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            self._load_error = (
                "sentence-transformers is not installed. "
                "Install with: pip install sentence-transformers"
            )
            raise ImportError(self._load_error)

        try:
            kwargs = {}
            if self._cache_dir:
                os.makedirs(self._cache_dir, exist_ok=True)
                kwargs["cache_folder"] = self._cache_dir

            self._model = SentenceTransformer(self._model_name, **kwargs)
            # Dimension verification
            test_vec = self._model.encode("test", normalize_embeddings=True)
            self._dimension = len(test_vec)
        except Exception as exc:
            self._load_error = str(exc)
            raise RuntimeError(f"Failed to load embedding model '{self._model_name}': {exc}")

    def embed_text(self, text: str) -> List[float]:
        self._ensure_loaded()
        vec = self._model.encode(str(text), normalize_embeddings=True)
        return vec.tolist()

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._ensure_loaded()
        clean_texts = [str(t) for t in texts]
        vecs = self._model.encode(clean_texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vecs]
