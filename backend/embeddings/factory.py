"""Factory for embedding providers."""

import os
from typing import Optional
from backend.embeddings.base import BaseEmbeddingProvider
from backend.embeddings.mock_provider import MockEmbeddingProvider
from backend.embeddings.pinecone_inference_provider import PineconeInferenceEmbeddingProvider
from backend.embeddings.sentence_transformer_provider import SentenceTransformerEmbeddingProvider

_CACHED_PROVIDER: Optional[BaseEmbeddingProvider] = None


def get_embedding_provider(provider_type: Optional[str] = None) -> BaseEmbeddingProvider:
    """Return the configured embedding provider singleton.

    Supported types:
      - 'pinecone_inference' (production default when PINECONE_API_KEY is present; 1024 dims, 0MB RAM)
      - 'sentence_transformers' (local PyTorch fallback; 384 dims)
      - 'mock' (offline deterministic semantic mock for tests & sandboxes)
    """
    global _CACHED_PROVIDER

    env_target = os.environ.get("EMBEDDING_PROVIDER")
    if provider_type:
        target = provider_type.lower()
    elif env_target:
        target = env_target.lower()
    elif os.environ.get("PINECONE_API_KEY", "").strip():
        # Default to Pinecone Inference in production when key is present to protect Render 512MB RAM
        target = "pinecone_inference"
    else:
        target = "mock"

    if _CACHED_PROVIDER is not None and getattr(_CACHED_PROVIDER, "_provider_type", None) == target:
        return _CACHED_PROVIDER

    if target == "mock":
        provider = MockEmbeddingProvider()
        setattr(provider, "_provider_type", "mock")
        _CACHED_PROVIDER = provider
        return provider

    if target in ("pinecone_inference", "pinecone"):
        provider = PineconeInferenceEmbeddingProvider()
        setattr(provider, "_provider_type", "pinecone_inference")
        _CACHED_PROVIDER = provider
        return provider

    # Local fallback
    provider = SentenceTransformerEmbeddingProvider()
    setattr(provider, "_provider_type", "sentence_transformers")
    _CACHED_PROVIDER = provider
    return provider
