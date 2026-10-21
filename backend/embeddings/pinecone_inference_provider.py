"""Pinecone Inference Embedding Provider.

Uses Pinecone's fully-hosted cloud inference API (pc.inference.embed)
to generate dense multilingual embeddings directly on Pinecone infrastructure.
Eliminates local PyTorch/model memory footprint on Render.

Model: multilingual-e5-large (Microsoft)
Dimension: 1024
Metric: Cosine
Max Tokens: 507
Pricing: $0.08 per 1 million tokens (Free tier includes monthly token allocation)
"""

import os
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

from backend.embeddings.base import BaseEmbeddingProvider


class PineconeInferenceEmbeddingProvider(BaseEmbeddingProvider):
    """Generates embeddings using Pinecone Hosted Inference API."""

    def __init__(
        self,
        model_name: str = "multilingual-e5-large",
        api_key: Optional[str] = None,
    ):
        self._model_name = model_name
        self._dimension = 1024
        self._api_key = api_key or os.environ.get("PINECONE_API_KEY", "").strip()
        self._pc = None
        self._init_error = None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def is_available(self) -> bool:
        try:
            self._ensure_init()
            return self._pc is not None
        except Exception:
            return False

    def _ensure_init(self):
        if self._pc is not None:
            return
        if not self._api_key:
            self._init_error = "PINECONE_API_KEY is not set in environment"
            raise ValueError(self._init_error)

        try:
            from pinecone import Pinecone
            self._pc = Pinecone(api_key=self._api_key)
        except Exception as exc:
            self._init_error = str(exc)
            raise RuntimeError(f"Failed to initialize Pinecone client: {exc}")

    def embed_text(self, text: str, input_type: str = "query") -> List[float]:
        """Embed a single string. input_type is 'query' or 'passage'."""
        self._ensure_init()
        clean = str(text or "").strip()
        if not clean:
            return [0.0] * self._dimension

        res = self._pc.inference.embed(
            model=self._model_name,
            inputs=[clean],
            parameters={"input_type": input_type},
        )
        vec = res[0].values if hasattr(res[0], "values") else res[0].get("values")
        return list(vec)

    def embed_batch(self, texts: List[str], input_type: str = "passage") -> List[List[float]]:
        """Embed a list of strings in batches of up to 64."""
        self._ensure_init()
        if not texts:
            return []

        clean_texts = [str(t or "").strip() for t in texts]
        results = []
        batch_size = 64

        for i in range(0, len(clean_texts), batch_size):
            chunk = clean_texts[i : i + batch_size]
            res = self._pc.inference.embed(
                model=self._model_name,
                inputs=chunk,
                parameters={"input_type": input_type},
            )
            for item in res:
                vec = item.values if hasattr(item, "values") else item.get("values")
                results.append(list(vec))

        return results
