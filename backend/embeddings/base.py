"""Base interface for embedding providers in Comment-Analyzer.

Provides a unified contract for converting text into dense float vectors
for Q&A search, supporting multilingual text (English, Hindi script, Hinglish).
"""

from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddingProvider(ABC):
    """Abstract base class for text embedding providers."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Unique identifier of the embedding model."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Output vector dimension."""
        pass

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Embed a single query or document string into a float vector."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of text strings into a list of float vectors."""
        pass
