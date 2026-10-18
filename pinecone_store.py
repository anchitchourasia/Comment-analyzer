"""Pinecone vector-database backend for Q&A storage.

Mirrors the exact same public interface that qa_engine.py previously
used with its JSON-file storage so the rest of the codebase is
unchanged.

Architecture:
  - Index name : "stream-assistant-qa"
  - Dimension  : 128  (sparse hash embedding; no ML model needed)
  - Metric     : "dotproduct"
  - Namespace  : channel_id (or "default" when None)

Each Pinecone vector represents one Q&A record:
  vector_id  = record["id"]          (e.g. "q_abc12345")
  values     = _text_to_vector(normalized_question)   # 128-dim hash
  metadata   = the full QA record dict (all scalar fields)

Why hash-embedding?  We already have a proven lexical + synonym
similarity scorer in qa_engine.calculate_score().  Pinecone is used
here purely as a durable, cloud-hosted KV store + approximate lookup;
the fine-grained scoring still runs locally so the matching quality is
identical to the JSON version.

All functions are thread-safe: they acquire PINECONE_LOCK before
touching the index.
"""

import hashlib
import os
import threading
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_NAME = "stream-assistant-qa"
VECTOR_DIM = 128          # hash-embedding dimension
_DEFAULT_NS = "default"   # namespace used when no channel_id supplied

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_pc = None          # Pinecone client instance
_index = None       # Pinecone Index handle
_init_error = None  # set when initialisation fails; enables graceful fallback
PINECONE_LOCK = threading.RLock()

_INITIALISED = False


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return os.environ.get("PINECONE_API_KEY", "").strip()


def _init():
    """Lazy singleton initialisation: connect to Pinecone and ensure the
    index exists.  Called the first time any public function is used."""
    global _pc, _index, _init_error, _INITIALISED

    if _INITIALISED:
        return _init_error is None

    _INITIALISED = True
    api_key = _get_api_key()
    if not api_key:
        _init_error = "PINECONE_API_KEY not set in environment / .env"
        return False

    try:
        from pinecone import Pinecone, ServerlessSpec

        _pc = Pinecone(api_key=api_key)

        # Create index if it does not exist yet
        existing = [idx.name for idx in _pc.list_indexes()]
        if INDEX_NAME not in existing:
            _pc.create_index(
                name=INDEX_NAME,
                dimension=VECTOR_DIM,
                metric="dotproduct",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
            # Wait until the index is ready (max 60 s)
            for _ in range(60):
                desc = _pc.describe_index(INDEX_NAME)
                if desc.status.ready:
                    break
                time.sleep(1)

        _index = _pc.Index(INDEX_NAME)
        return True

    except Exception as exc:
        _init_error = str(exc)
        return False


def is_available() -> bool:
    """Return True if Pinecone is configured and reachable."""
    with PINECONE_LOCK:
        return _init()


# ---------------------------------------------------------------------------
# Hash-based text → vector
# ---------------------------------------------------------------------------

def _text_to_vector(text: str) -> list[float]:
    """Map a normalised question string to a fixed-length float vector.

    We use a deterministic multi-hash scheme so that:
    - the same text always maps to the same vector
    - similar texts are NOT close (Pinecone is used as a KV store here,
      not for semantic-nearest-neighbour retrieval)
    """
    encoded = text.encode("utf-8")
    vec = [0.0] * VECTOR_DIM
    for i in range(VECTOR_DIM):
        h = hashlib.sha256(encoded + i.to_bytes(2, "big")).digest()
        # Map first byte to [-1, 1]
        vec[i] = (h[0] - 127.5) / 127.5
    # L2-normalise
    norm = (sum(v * v for v in vec) ** 0.5) or 1.0
    return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# Namespace helper
# ---------------------------------------------------------------------------

def _ns(channel_id: str | None) -> str:
    if not channel_id:
        return _DEFAULT_NS
    return str(channel_id).strip() or _DEFAULT_NS


# ---------------------------------------------------------------------------
# Internal helpers that work directly with Pinecone
# ---------------------------------------------------------------------------

def _record_to_pinecone_meta(record: dict) -> dict:
    """Flatten a QA record into Pinecone-storable metadata (scalars only)."""
    meta = {k: v for k, v in record.items()
            if isinstance(v, (str, int, float, bool)) and v is not None}
    # Store list of examples as a joined string (Pinecone metadata values
    # must be scalars or lists-of-strings; we keep it simple with join).
    examples = record.get("original_question_examples", [])
    if isinstance(examples, list):
        meta["original_question_examples"] = "|||".join(str(e) for e in examples)
    return meta


def _meta_to_record(meta: dict) -> dict:
    """Restore a QA record from Pinecone metadata."""
    record = dict(meta)
    raw_ex = record.get("original_question_examples", "")
    if isinstance(raw_ex, str):
        record["original_question_examples"] = (
            [e for e in raw_ex.split("|||") if e] if raw_ex else []
        )
    # Coerce numeric fields back
    record["usage_count"] = int(record.get("usage_count", 0) or 0)
    record["cooldown_seconds"] = int(record.get("cooldown_seconds", 60) or 60)
    record["auto_reply"] = bool(record.get("auto_reply", False))
    record["last_used_at"] = record.get("last_used_at") or None
    return record


def _fetch_all(namespace: str) -> list[dict]:
    """Fetch ALL vectors from a namespace and return as QA record dicts.

    Pinecone's list() API gives IDs; we then fetch in batches of 100.
    """
    if not _index:
        return []

    try:
        all_ids = []
        for id_page in _index.list(namespace=namespace):
            # Pinecone SDK v5+ / v10 returns ListResponse objects with .vectors
            vec_items = getattr(id_page, "vectors", None)
            if vec_items is not None:
                for item in vec_items:
                    vid = getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else str(item))
                    if vid:
                        all_ids.append(str(vid))
            elif isinstance(id_page, (list, tuple)):
                for item in id_page:
                    vid = getattr(item, "id", None) or (item.get("id") if isinstance(item, dict) else str(item))
                    if vid:
                        all_ids.append(str(vid))
            elif isinstance(id_page, str):
                all_ids.append(id_page)

        if not all_ids:
            return []

        records = []
        batch_size = 100
        for i in range(0, len(all_ids), batch_size):
            batch_ids = all_ids[i: i + batch_size]
            result = _index.fetch(ids=batch_ids, namespace=namespace)
            vectors = getattr(result, "vectors", None)
            if vectors is None and isinstance(result, dict):
                vectors = result.get("vectors")
            if vectors and hasattr(vectors, "values"):
                for v in vectors.values():
                    meta = getattr(v, "metadata", None) or (v.get("metadata") if isinstance(v, dict) else None)
                    if meta:
                        records.append(_meta_to_record(meta))
            elif vectors and isinstance(vectors, dict):
                for _, v in vectors.items():
                    meta = getattr(v, "metadata", None) or (v.get("metadata") if isinstance(v, dict) else None)
                    if meta:
                        records.append(_meta_to_record(meta))
        return records

    except Exception as exc:
        print(f"Error in _fetch_all from Pinecone: {exc}")
        return []


# ---------------------------------------------------------------------------
# In-memory Write-Through Cache (Immediate consistency + 0ms local reads)
# ---------------------------------------------------------------------------

_records_cache = {}    # {namespace: {record_id: record_dict}}
_cache_loaded = set()  # set of namespaces whose records have been hydrated from Pinecone


def _ensure_cache_loaded(namespace: str) -> None:
    """Hydrate in-memory cache from Pinecone on first access for a namespace."""
    if namespace not in _cache_loaded:
        records = _fetch_all(namespace)
        _records_cache[namespace] = {r["id"]: r for r in records if r.get("id")}
        _cache_loaded.add(namespace)


def load_qa_data(channel_id: str | None = None) -> list[dict]:
    """Load all QA records for the given channel. Uses write-through cache backed by Pinecone."""
    with PINECONE_LOCK:
        if not _init():
            return []
        ns = _ns(channel_id)
        _ensure_cache_loaded(ns)
        return list(_records_cache[ns].values())


def save_qa_data(records: list[dict], channel_id: str | None = None) -> list[dict]:
    """Persist QA records to Pinecone. Updates cache and upserts all records into the channel namespace."""
    with PINECONE_LOCK:
        if not _init():
            return records

        ns = _ns(channel_id)
        _records_cache[ns] = {r["id"]: r for r in records if r.get("id")}
        _cache_loaded.add(ns)

        try:
            vectors = []
            for record in records:
                rec_id = record.get("id")
                norm_q = record.get("normalized_question", "")
                if not rec_id or not norm_q:
                    continue
                vectors.append({
                    "id": rec_id,
                    "values": _text_to_vector(norm_q),
                    "metadata": _record_to_pinecone_meta(record),
                })

            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                _index.upsert(vectors=vectors[i: i + batch_size], namespace=ns)

        except Exception as exc:
            print(f"Error in save_qa_data to Pinecone: {exc}")

        return records


def upsert_record(record: dict, channel_id: str | None = None) -> None:
    """Upsert a single QA record into Pinecone and update cache immediately."""
    with PINECONE_LOCK:
        if not _init():
            return

        ns = _ns(channel_id)
        _ensure_cache_loaded(ns)

        rec_id = record.get("id")
        norm_q = record.get("normalized_question", "")
        if not rec_id or not norm_q:
            return

        # Update cache immediately
        _records_cache[ns][rec_id] = record

        try:
            _index.upsert(
                vectors=[{
                    "id": rec_id,
                    "values": _text_to_vector(norm_q),
                    "metadata": _record_to_pinecone_meta(record),
                }],
                namespace=ns,
            )
        except Exception as exc:
            print(f"Error in upsert_record to Pinecone: {exc}")


def delete_record(record_id: str, channel_id: str | None = None) -> bool:
    """Delete one QA record from Pinecone by ID and drop from cache."""
    with PINECONE_LOCK:
        if not _init():
            return False

        ns = _ns(channel_id)
        _ensure_cache_loaded(ns)
        _records_cache[ns].pop(record_id, None)

        try:
            _index.delete(ids=[record_id], namespace=ns)
            return True
        except Exception as exc:
            print(f"Error deleting record {record_id} from Pinecone: {exc}")
            return False


def clear_namespace(channel_id: str | None = None) -> None:
    """Delete all QA records for a channel (used on session reset)."""
    with PINECONE_LOCK:
        if not _init():
            return

        ns = _ns(channel_id)
        _records_cache[ns] = {}
        _cache_loaded.add(ns)

        try:
            _index.delete(delete_all=True, namespace=ns)
        except Exception:
            pass


def find_by_normalized_question(
    normalized_q: str,
    channel_id: str | None = None,
    top_k: int = 10,
) -> list[dict]:
    """ANN search: return up to top_k candidates by vector similarity.

    The caller (qa_engine.find_best_answer) still runs its own precise
    scoring on the candidates, so this is just a fast pre-filter.
    """
    with PINECONE_LOCK:
        if not _init():
            return []

        ns = _ns(channel_id)
        try:
            result = _index.query(
                vector=_text_to_vector(normalized_q),
                top_k=top_k,
                namespace=ns,
                include_metadata=True,
            )
            matches = result.get("matches") or (result.matches if hasattr(result, "matches") else [])
            records = []
            for m in matches:
                meta = m.get("metadata") if isinstance(m, dict) else m.metadata
                if meta:
                    records.append(_meta_to_record(meta))
            return records
        except Exception:
            return []


def get_index_stats(channel_id: str | None = None) -> dict:
    """Return basic stats about the Pinecone index / namespace."""
    with PINECONE_LOCK:
        if not _init():
            return {"available": False, "error": _init_error}

        try:
            stats = _index.describe_index_stats()
            ns = _ns(channel_id)
            vector_count = 0
            namespaces = getattr(stats, "namespaces", None)
            if isinstance(namespaces, dict):
                ns_obj = namespaces.get(ns)
                if ns_obj is not None:
                    vector_count = getattr(ns_obj, "vector_count", 0)
                elif ns == "default" and hasattr(stats, "total_vector_count"):
                    vector_count = stats.total_vector_count
            elif hasattr(stats, "total_vector_count"):
                vector_count = stats.total_vector_count

            return {
                "available": True,
                "index_name": INDEX_NAME,
                "namespace": ns,
                "vector_count": vector_count,
                "dimension": getattr(stats, "dimension", VECTOR_DIM),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}

