"""Pinecone client for genuine multilingual semantic retrieval and reranking.

Manages the semantic vector index (default: "stream-assistant-qa-semantic", 1024 dims, cosine)
with strict channel namespace isolation and metadata filtering.
Preserves the existing 128-dim legacy index ("stream-assistant-qa") intact.
"""

import os
import threading
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants & Configuration
# ---------------------------------------------------------------------------
SEMANTIC_INDEX_NAME = os.environ.get("PINECONE_SEMANTIC_INDEX_NAME", "stream-assistant-qa-semantic")
SEMANTIC_DIMENSION = int(os.environ.get("PINECONE_SEMANTIC_DIMENSION", "1024"))
SEMANTIC_METRIC = "cosine"
RERANK_MODEL = os.environ.get("PINECONE_RERANK_MODEL", "bge-reranker-v2-m3")

_PINECONE_LOCK = threading.RLock()
_pc_client = None
_index_handle = None
_init_attempted = False
_init_error: Optional[str] = None

# Mock index hook for testing
_mock_index = None
_mock_rerank = None


def set_mock_index(mock_obj, mock_rerank_obj=None):
    """Inject mock objects for testing without connecting to Pinecone."""
    global _mock_index, _mock_rerank
    _mock_index = mock_obj
    _mock_rerank = mock_rerank_obj


def get_semantic_index_config() -> Dict[str, Any]:
    """Return the proposed or active semantic index configuration."""
    return {
        "index_name": SEMANTIC_INDEX_NAME,
        "dimension": SEMANTIC_DIMENSION,
        "metric": SEMANTIC_METRIC,
        "spec": {"cloud": "aws", "region": "us-east-1"},
    }


def _get_api_key() -> str:
    return os.environ.get("PINECONE_API_KEY", "").strip()


def _init_semantic_index() -> bool:
    """Connect to Pinecone and check if the semantic index exists.

    SAFEGUARD: Never automatically creates or deletes remote indexes.
    If the index is missing, reports it cleanly as unavailable until created.
    """
    global _pc_client, _index_handle, _init_attempted, _init_error

    if _mock_index is not None:
        return True

    with _PINECONE_LOCK:
        if _init_attempted:
            return _index_handle is not None

        _init_attempted = True
        api_key = _get_api_key()
        if not api_key:
            _init_error = "PINECONE_API_KEY not set in environment"
            return False

        try:
            from pinecone import Pinecone

            _pc_client = Pinecone(api_key=api_key)
            existing_indexes = [idx.name for idx in _pc_client.list_indexes()]

            if SEMANTIC_INDEX_NAME not in existing_indexes:
                _init_error = (
                    f"Semantic index '{SEMANTIC_INDEX_NAME}' does not exist on Pinecone. "
                    f"Existing indexes: {existing_indexes}. "
                    "Index creation requires explicit approval."
                )
                return False

            _index_handle = _pc_client.Index(SEMANTIC_INDEX_NAME)
            _init_error = None
            return True

        except Exception as exc:
            _init_error = str(exc)
            return False


def is_semantic_pinecone_available() -> bool:
    """Return True if Pinecone semantic index is reachable and ready."""
    if _mock_index is not None:
        return True
    return _init_semantic_index()


def get_semantic_pinecone_stats(channel_id: Optional[str] = None) -> Dict[str, Any]:
    """Return stats for the semantic Pinecone index and the channel namespace."""
    if _mock_index is not None:
        return {
            "available": True,
            "index_name": SEMANTIC_INDEX_NAME,
            "namespace": channel_id or "default",
            "dimension": SEMANTIC_DIMENSION,
            "metric": SEMANTIC_METRIC,
            "is_mock": True,
        }

    with _PINECONE_LOCK:
        ready = _init_semantic_index()
        if not ready:
            return {
                "available": False,
                "index_name": SEMANTIC_INDEX_NAME,
                "dimension": SEMANTIC_DIMENSION,
                "metric": SEMANTIC_METRIC,
                "error": _init_error,
            }

        try:
            stats = _index_handle.describe_index_stats()
            ns = channel_id or "default"
            ns_stats = getattr(stats, "namespaces", {}) or {}
            vector_count = 0
            if isinstance(ns_stats, dict) and ns in ns_stats:
                vector_count = getattr(ns_stats[ns], "vector_count", 0)

            return {
                "available": True,
                "index_name": SEMANTIC_INDEX_NAME,
                "namespace": ns,
                "vector_count": vector_count,
                "total_vector_count": getattr(stats, "total_vector_count", 0),
                "dimension": getattr(stats, "dimension", SEMANTIC_DIMENSION),
                "metric": SEMANTIC_METRIC,
            }
        except Exception as exc:
            return {
                "available": False,
                "index_name": SEMANTIC_INDEX_NAME,
                "dimension": SEMANTIC_DIMENSION,
                "metric": SEMANTIC_METRIC,
                "error": str(exc),
            }


def query_semantic_index(
    vector: List[float],
    channel_id: str,
    top_k: int = 5,
    filter_approved_only: bool = True,
) -> List[Dict[str, Any]]:
    """Execute ANN similarity query within the channel namespace with metadata filtering.

    TENANT ISOLATION:
    Fails closed if channel_id is empty or None.
    """
    if not channel_id or not str(channel_id).strip():
        raise ValueError("channel_id is required for tenant isolation; cannot query global namespace")

    target_index = _mock_index or _index_handle
    if target_index is None:
        if not _init_semantic_index():
            return []
        target_index = _index_handle

    query_filter = {"status": {"$eq": "approved"}} if filter_approved_only else None

    try:
        kwargs = {
            "vector": vector,
            "namespace": str(channel_id).strip(),
            "top_k": top_k,
            "include_metadata": True,
        }
        if query_filter:
            kwargs["filter"] = query_filter

        result = target_index.query(**kwargs)

        matches = []
        raw_matches = result.get("matches") if isinstance(result, dict) else getattr(result, "matches", [])
        for m in raw_matches:
            vid = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
            score = m.get("score") if isinstance(m, dict) else getattr(m, "score", 0.0)
            meta = m.get("metadata") if isinstance(m, dict) else getattr(m, "metadata", {})
            if vid:
                matches.append({
                    "id": str(vid),
                    "score": float(score or 0.0),
                    "metadata": dict(meta or {}),
                })
        return matches
    except Exception as exc:
        print(f"Error querying semantic index: {exc}")
        return []


def rerank_candidates(
    query: str,
    documents: List[Dict[str, str]],
    top_n: int = 3,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Execute hosted Pinecone reranking on retrieved candidate answers.

    NOTE: Relevance score is an uncalibrated ranking signal, NOT a probability
    and NOT an auto-posting gate.
    """
    if _mock_rerank is not None:
        return _mock_rerank(query, documents, top_n)

    api_key = _get_api_key()
    if not api_key or not documents:
        return []

    try:
        from pinecone import Pinecone
        pc = _pc_client or Pinecone(api_key=api_key)
        target_model = model or RERANK_MODEL

        # Format documents: list of dicts with 'text' field
        formatted = [{"id": str(i), "text": str(d.get("text") or d.get("answer_text") or "")}
                     for i, d in enumerate(documents)]

        res = pc.inference.rerank(
            model=target_model,
            query=str(query),
            documents=formatted,
            top_n=min(top_n, len(formatted)),
            return_documents=False,
        )

        ranked = []
        data_items = getattr(res, "data", []) or []
        for item in data_items:
            idx = getattr(item, "index", None)
            score = getattr(item, "score", 0.0)
            if idx is not None and idx < len(documents):
                ranked.append({
                    "document": documents[idx],
                    "rerank_score": float(score),
                    "original_index": idx,
                })
        return ranked
    except Exception as exc:
        print(f"Warning: Pinecone reranking failed: {exc}")
        return []


def upsert_semantic_vectors(
    vectors: List[Dict[str, Any]],
    channel_id: str,
    batch_size: int = 50,
) -> int:
    """Upsert vectors into the channel's namespace. Returns count of upserted vectors."""
    if not channel_id or not str(channel_id).strip():
        raise ValueError("channel_id is required for tenant isolation")
    if not vectors:
        return 0

    target_index = _mock_index or _index_handle
    if target_index is None:
        if not _init_semantic_index():
            raise RuntimeError(f"Cannot upsert: semantic index unavailable ({_init_error})")
        target_index = _index_handle

    upserted = 0
    for i in range(0, len(vectors), batch_size):
        chunk = vectors[i : i + batch_size]
        target_index.upsert(vectors=chunk, namespace=str(channel_id).strip())
        upserted += len(chunk)
    return upserted


def delete_semantic_vector(record_id: str, channel_id: str) -> bool:
    """Delete a single vector from the channel namespace."""
    if not channel_id or not record_id:
        return False

    target_index = _mock_index or _index_handle
    if target_index is None:
        if not _init_semantic_index():
            return False
        target_index = _index_handle

    try:
        target_index.delete(ids=[record_id], namespace=str(channel_id).strip())
        return True
    except Exception as exc:
        print(f"Error deleting semantic vector {record_id}: {exc}")
        return False
