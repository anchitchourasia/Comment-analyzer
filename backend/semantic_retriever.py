"""Genuine Multilingual Semantic Retriever for Live Chat Q&A.

Coordinates:
  1. Dense text embeddings via BaseEmbeddingProvider (default: Pinecone Inference multilingual-e5-large).
  2. Pinecone vector similarity search with strict channel namespace isolation and approved metadata filtering.
  3. Authoritative Q&A record verification (checks approval status & fresh answer).
  4. Hybrid ranking, optional Pinecone reranking stage, and transparent lexical fallback.
"""

import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import qa_engine
from backend.embeddings.base import BaseEmbeddingProvider
from backend.embeddings.factory import get_embedding_provider
import backend.semantic_pinecone as semantic_pinecone


@dataclass
class SemanticRetrievalResult:
    """Typed result from the semantic retriever."""
    matched_record: Optional[Dict[str, Any]]
    score: float
    match_type: str  # "exact_keyword" | "semantic" | "hybrid" | "lexical_fallback" | "none"
    semantic_score: Optional[float]  # None if semantic search was bypassed
    lexical_score: float
    ranking_score: float
    model_name: str
    status: str  # "success" | "fallback" | "no_match" | "failed_closed"
    fallback_reason: Optional[str] = None
    rerank_score: Optional[float] = None
    top_candidates: List[Dict[str, Any]] = field(default_factory=list)


INTENT_WORDS = {
    "when", "where", "what", "which", "who", "how", "why",
    "kab", "kahan", "kaise", "kya", "kyun", "kitna", "kitne", "kaunsa", "kaun",
    "nahi", "not", "no", "never", "mat",
}


def preprocess_for_embedding(text: str) -> str:
    """Clean text for embedding generation while preserving intent-bearing words."""
    if not text:
        return ""
    s = re.sub(r"https?://\S+|www\.\S+", " ", str(text))
    s = re.sub(r"[^\w\s\?\u0900-\u097F]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 <= 1e-9 or norm2 <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, dot / (norm1 * norm2)))


class SemanticQARetriever:
    """Authoritative semantic retriever with tenant isolation and fallback."""

    def __init__(
        self,
        embedding_provider: Optional[BaseEmbeddingProvider] = None,
        enable_reranking: bool = False,
    ):
        self._provider = embedding_provider
        self.enable_reranking = enable_reranking

    @property
    def provider(self) -> BaseEmbeddingProvider:
        if self._provider is None:
            self._provider = get_embedding_provider()
        return self._provider

    def retrieve(
        self,
        query: str,
        channel_id: Optional[str] = None,
        top_k: int = 3,
        threshold: float = 0.50,
        bypass_keyword_triggers: bool = False,
    ) -> SemanticRetrievalResult:
        """Execute semantic retrieval for a query against approved Q&A.

        TENANT ISOLATION:
        When channel_id is provided, Pinecone queries are strictly scoped to
        that namespace. If channel_id is None, Pinecone query is skipped to prevent
        cross-tenant leakage, but local in-memory session records are evaluated.

        bypass_keyword_triggers:
        Sandbox-only flag to bypass exact keyword matching and directly evaluate
        dense vector retrieval from Pinecone.
        """
        clean_ch_id = (channel_id or "").strip()
        clean_query = preprocess_for_embedding(query)
        if not clean_query:
            return SemanticRetrievalResult(
                matched_record=None,
                score=0.0,
                match_type="none",
                semantic_score=None,
                lexical_score=0.0,
                ranking_score=0.0,
                model_name=self.provider.model_name if self.provider else "none",
                status="no_match",
                fallback_reason="Empty query text",
            )

        # 1. Authoritative record bank check
        approved_records = [
            r for r in qa_engine.load_qa_data(channel_id=clean_ch_id or None)
            if r.get("status") == "approved"
        ]
        if not approved_records:
            return SemanticRetrievalResult(
                matched_record=None,
                score=0.0,
                match_type="none",
                semantic_score=None,
                lexical_score=0.0,
                ranking_score=0.0,
                model_name=self.provider.model_name if self.provider else "none",
                status="no_match",
                fallback_reason="No approved Q&A records exist in memory",
            )

        records_by_id = {r["id"]: r for r in approved_records if r.get("id")}

        # 2. Check for exact or keyword trigger match first (unless explicitly bypassed)
        if not bypass_keyword_triggers:
            lex_record, lex_score = qa_engine.find_best_answer(
                query, qa_data=approved_records, channel_id=clean_ch_id or None
            )
            if lex_record and lex_score >= 0.80:
                return SemanticRetrievalResult(
                    matched_record=lex_record,
                    score=lex_score,
                    match_type="exact_keyword",
                    semantic_score=None,  # Bypassed: show N/A
                    lexical_score=lex_score,
                    ranking_score=lex_score,
                    model_name="keyword_engine",
                    status="success",
                    fallback_reason="Exact keyword trigger matched; semantic search bypassed",
                    top_candidates=[{"record": lex_record, "score": lex_score, "match_type": "exact_keyword"}],
                )

        # 3. Pinecone Semantic Search (only when clean_ch_id is provided)
        semantic_candidates = []
        pinecone_ready = False
        fallback_err = None

        if clean_ch_id:
            pinecone_ready = semantic_pinecone.is_semantic_pinecone_available()
            if pinecone_ready:
                try:
                    # Input type query for Pinecone Inference
                    if hasattr(self.provider, "embed_text") and "input_type" in self.provider.embed_text.__code__.co_varnames:
                        query_vec = self.provider.embed_text(clean_query, input_type="query")
                    else:
                        query_vec = self.provider.embed_text(clean_query)

                    matches = semantic_pinecone.query_semantic_index(
                        vector=query_vec,
                        channel_id=clean_ch_id,
                        top_k=top_k * 2,
                        filter_approved_only=True,
                    )
                    for m in matches:
                        rec_id = m.get("id")
                        if rec_id in records_by_id:
                            auth_rec = records_by_id[rec_id]
                            raw_sim = float(m.get("score", 0.0))
                            semantic_candidates.append((auth_rec, raw_sim))
                except Exception as exc:
                    pinecone_ready = False
                    fallback_err = f"Pinecone query exception: {exc}"
            else:
                fallback_err = "Pinecone semantic index not provisioned or unavailable"
        else:
            fallback_err = "No channel_id provided; remote Pinecone search skipped to prevent cross-tenant leak"

        # 4. If Pinecone yielded no candidates, compute local vector similarity over channel's records
        if not semantic_candidates and self.provider is not None:
            try:
                if hasattr(self.provider, "embed_text") and "input_type" in self.provider.embed_text.__code__.co_varnames:
                    query_vec = self.provider.embed_text(clean_query, input_type="query")
                else:
                    query_vec = self.provider.embed_text(clean_query)

                for rec in approved_records:
                    canonical_q = rec.get("normalized_question", "")
                    ex_list = rec.get("original_question_examples", []) or []
                    all_phrasings = [canonical_q] + [e for e in ex_list if e]

                    best_rec_sim = 0.0
                    for phr in all_phrasings:
                        c_clean = preprocess_for_embedding(phr)
                        if hasattr(self.provider, "embed_text") and "input_type" in self.provider.embed_text.__code__.co_varnames:
                            c_vec = self.provider.embed_text(c_clean, input_type="passage")
                        else:
                            c_vec = self.provider.embed_text(c_clean)
                        sim = cosine_similarity(query_vec, c_vec)
                        if sim > best_rec_sim:
                            best_rec_sim = sim

                    if best_rec_sim > 0.0:
                        semantic_candidates.append((rec, best_rec_sim))
                semantic_candidates.sort(key=lambda x: x[1], reverse=True)
            except Exception as exc:
                fallback_err = f"Semantic embedding error: {exc}"

        # 5. Hybrid ranking & Optional Reranking Stage
        if semantic_candidates:
            evaluated_candidates = []
            for rec, sem_score in semantic_candidates[:top_k]:
                _, c_lex_score = qa_engine.find_best_answer(
                    query, qa_data=[rec], channel_id=clean_ch_id or None
                )

                if c_lex_score > 0 and not bypass_keyword_triggers:
                    ranking_score = round((0.70 * sem_score) + (0.30 * c_lex_score), 4)
                    m_type = "hybrid"
                else:
                    ranking_score = round(sem_score, 4)
                    m_type = "semantic"

                evaluated_candidates.append({
                    "record": rec,
                    "ranking_score": ranking_score,
                    "semantic_score": round(sem_score, 4),
                    "lexical_score": round(c_lex_score, 4),
                    "match_type": m_type,
                })

            # Optional Second-Stage Reranking via Pinecone
            rerank_score = None
            if self.enable_reranking and len(evaluated_candidates) > 0:
                try:
                    docs = [{"id": c["record"]["id"], "text": c["record"]["answer_text"]} for c in evaluated_candidates]
                    rerank_res = semantic_pinecone.rerank_candidates(query, docs, top_n=top_k)
                    if rerank_res:
                        rerank_map = {r["document"]["id"]: r["rerank_score"] for r in rerank_res}
                        for cand in evaluated_candidates:
                            cid = cand["record"]["id"]
                            if cid in rerank_map:
                                cand["rerank_score"] = rerank_map[cid]
                        rerank_score = evaluated_candidates[0].get("rerank_score")
                except Exception as exc:
                    print(f"Reranking pass skipped: {exc}")

            evaluated_candidates.sort(key=lambda x: x["ranking_score"], reverse=True)
            best = evaluated_candidates[0]

            if best["ranking_score"] >= threshold:
                return SemanticRetrievalResult(
                    matched_record=best["record"],
                    score=best["ranking_score"],
                    match_type=best["match_type"],
                    semantic_score=best["semantic_score"],
                    lexical_score=best["lexical_score"],
                    ranking_score=best["ranking_score"],
                    model_name=self.provider.model_name,
                    status="success",
                    rerank_score=rerank_score,
                    top_candidates=evaluated_candidates,
                )
            else:
                return SemanticRetrievalResult(
                    matched_record=None,
                    score=best["ranking_score"],
                    match_type="none",
                    semantic_score=best["semantic_score"],
                    lexical_score=best["lexical_score"],
                    ranking_score=best["ranking_score"],
                    model_name=self.provider.model_name,
                    status="no_match",
                    fallback_reason=f"Top candidate score {best['ranking_score']} below threshold {threshold}",
                    rerank_score=rerank_score,
                    top_candidates=evaluated_candidates,
                )

        # 6. Fall back explicitly to lexical matching
        lex_record, lex_score = qa_engine.find_best_answer(
            query, qa_data=approved_records, channel_id=clean_ch_id or None
        )
        if lex_record and lex_score >= threshold:
            return SemanticRetrievalResult(
                matched_record=lex_record,
                score=lex_score,
                match_type="lexical_fallback",
                semantic_score=None,  # Bypassed
                lexical_score=round(lex_score, 4),
                ranking_score=round(lex_score, 4),
                model_name="lexical_engine",
                status="fallback",
                fallback_reason=fallback_err or "Semantic retriever yielded no candidates; fell back to lexical engine",
                top_candidates=[{"record": lex_record, "score": lex_score, "match_type": "lexical_fallback"}],
            )

        return SemanticRetrievalResult(
            matched_record=None,
            score=lex_score,
            match_type="none",
            semantic_score=None,
            lexical_score=round(lex_score, 4),
            ranking_score=round(lex_score, 4),
            model_name="lexical_engine",
            status="no_match",
            fallback_reason=fallback_err or "No match found above threshold in lexical fallback",
        )
