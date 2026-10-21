"""Evaluation of 25-query multilingual benchmark using the REAL Pinecone-hosted multilingual-e5-large model.

Measures:
  - Top-1 accuracy
  - Recall@3
  - Incorrect matches (false-positives)
  - Abstention rate on noise/negation queries
  - Actual per-query embedding and rerank latency
"""

import io
import os
import sys
import time
from pathlib import Path

# Force utf-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from backend.embeddings.pinecone_inference_provider import PineconeInferenceEmbeddingProvider
from backend.semantic_retriever import cosine_similarity, preprocess_for_embedding
import backend.semantic_pinecone as semantic_pinecone

BENCHMARK_RECORDS = [
    {
        "id": "q_sched_01",
        "canonical": "what time does the stream start",
        "examples": ["what time does the stream start", "when are you live"],
        "answer": "Stream starts daily at 8 PM IST!",
    },
    {
        "id": "q_plat_02",
        "canonical": "where do you stream",
        "examples": ["where do you stream", "which platform are you streaming on"],
        "answer": "We stream live exclusively on YouTube!",
    },
    {
        "id": "q_game_03",
        "canonical": "which game are you playing today",
        "examples": ["which game are you playing today", "game name please"],
        "answer": "Today we are playing GTA V RP!",
    },
    {
        "id": "q_cam_04",
        "canonical": "which camera do you use",
        "examples": ["which camera do you use", "what camera is this"],
        "answer": "Sony ZV-E10 with 16mm f/1.4 lens.",
    },
    {
        "id": "q_price_05",
        "canonical": "what is the price of your camera",
        "examples": ["what is the price of your camera", "how much does your camera cost"],
        "answer": "The camera body was around 65,000 INR.",
    },
    {
        "id": "q_mic_06",
        "canonical": "which microphone do you use",
        "examples": ["which microphone do you use", "what mic are you using"],
        "answer": "Shure SM7B with GoXLR interface.",
    },
    {
        "id": "q_specs_07",
        "canonical": "what are your pc specs",
        "examples": ["what are your pc specs", "pc specifications"],
        "answer": "RTX 4090, i9-14900K, 64GB DDR5 RAM.",
    },
]

LABELED_QUERIES = [
    # --- English Paraphrases ---
    {"query": "When are you going live today?", "expected": "q_sched_01", "category": "EN_Paraphrase"},
    {"query": "What is your broadcast schedule?", "expected": "q_sched_01", "category": "EN_Paraphrase"},
    {"query": "Which platform are you hosting on?", "expected": "q_plat_02", "category": "EN_Paraphrase"},
    {"query": "What mic model is in your setup?", "expected": "q_mic_06", "category": "EN_Paraphrase"},
    {"query": "What is your computer hardware specs?", "expected": "q_specs_07", "category": "EN_Paraphrase"},

    # --- Hindi Script (Devanagari) ---
    {"query": "स्ट्रीम कब शुरू होगा?", "expected": "q_sched_01", "category": "Hindi_Script"},
    {"query": "आप कौन सा कैमरा इस्तेमाल करते हैं?", "expected": "q_cam_04", "category": "Hindi_Script"},
    {"query": "माइक कौन सा है?", "expected": "q_mic_06", "category": "Hindi_Script"},

    # --- Hinglish Queries ---
    {"query": "Stream kab start hoga?", "expected": "q_sched_01", "category": "Hinglish"},
    {"query": "Stream kahan hoga?", "expected": "q_plat_02", "category": "Hinglish_Contrasting"},
    {"query": "Stream par kaunsa game hoga?", "expected": "q_game_03", "category": "Hinglish_Contrasting"},
    {"query": "Camera kaunsa hai?", "expected": "q_cam_04", "category": "Hinglish_Contrasting"},
    {"query": "Camera ka price kya hai?", "expected": "q_price_05", "category": "Hinglish_Contrasting"},
    {"query": "Mic kaunsa hai?", "expected": "q_mic_06", "category": "Hinglish_Contrasting"},
    {"query": "Aaj kitne baje shuru karoge live?", "expected": "q_sched_01", "category": "Hinglish"},
    {"query": "Bhai camera kitne ka pada?", "expected": "q_price_05", "category": "Hinglish"},
    {"query": "Kahan live aate ho?", "expected": "q_plat_02", "category": "Hinglish"},

    # --- Typos & Slang ---
    {"query": "wat camra u use bro", "expected": "q_cam_04", "category": "Typo_Slang"},
    {"query": "spex of pc pls", "expected": "q_specs_07", "category": "Typo_Slang"},

    # --- Negation & Contrasting Opposites (Must NOT match hardware Q&A) ---
    {"query": "Mic nahi chal raha hai awaz nahi aa rahi", "expected": None, "category": "Negation_Issue"},
    {"query": "Camera freeze ho gaya", "expected": None, "category": "Negation_Issue"},

    # --- Unrelated Noise (Must Abstain / Score < 0.50) ---
    {"query": "What is the capital of France?", "expected": None, "category": "Unrelated_Noise"},
    {"query": "How to bake a chocolate cake?", "expected": None, "category": "Unrelated_Noise"},
    {"query": "Tell me a funny joke", "expected": None, "category": "Unrelated_Noise"},
    {"query": "Who is the prime minister of Japan?", "expected": None, "category": "Unrelated_Noise"},
]


def run_real_evaluation():
    print("=" * 65)
    print("Evaluating REAL Pinecone-Hosted Model: multilingual-e5-large (1024 dims)")
    print("=" * 65)

    provider = PineconeInferenceEmbeddingProvider(model_name="multilingual-e5-large")

    print("\n1. Embedding canonical passages via Pinecone Inference...")
    t0 = time.time()
    record_embeddings = []
    for rec in BENCHMARK_RECORDS:
        phrasings = [rec["canonical"]] + rec["examples"]
        vecs = provider.embed_batch([preprocess_for_embedding(p) for p in phrasings], input_type="passage")
        record_embeddings.append({"rec": rec, "vectors": vecs})
    passage_time = time.time() - t0
    print(f"   Passage embedding completed in {passage_time:.2f}s ({len(record_embeddings)} records)")

    print("\n2. Evaluating 25 test queries against passages...")
    top1_correct = 0
    recall_at_3 = 0
    incorrect_matches = 0
    correct_abstentions = 0
    total_noise_queries = sum(1 for q in LABELED_QUERIES if q["expected"] is None)
    total_valid_queries = sum(1 for q in LABELED_QUERIES if q["expected"] is not None)

    embed_latencies = []
    threshold = 0.50

    for item in LABELED_QUERIES:
        query_text = item["query"]
        expected_id = item["expected"]

        t_start = time.time()
        q_vec = provider.embed_text(preprocess_for_embedding(query_text), input_type="query")
        embed_latencies.append((time.time() - t_start) * 1000)

        # Score against all passages
        scored = []
        for item_emb in record_embeddings:
            rec = item_emb["rec"]
            best_sim = max(cosine_similarity(q_vec, v) for v in item_emb["vectors"])
            scored.append({"id": rec["id"], "score": best_sim, "canonical": rec["canonical"]})

        scored.sort(key=lambda x: x["score"], reverse=True)
        top1 = scored[0]
        top3_ids = [s["id"] for s in scored[:3]]

        matched_id = top1["id"] if top1["score"] >= threshold else None

        if expected_id is None:
            if matched_id is None:
                top1_correct += 1
                correct_abstentions += 1
                status = "CORRECT_ABSTAIN"
            else:
                incorrect_matches += 1
                status = f"FALSE_POSITIVE ({matched_id})"
        else:
            if matched_id == expected_id:
                top1_correct += 1
                status = "CORRECT_TOP1"
            elif expected_id in top3_ids and top1["score"] >= threshold:
                incorrect_matches += 1
                status = f"WRONG_TOP1 (expected {expected_id}, got {matched_id})"
            else:
                status = f"MISSED (Score {top1['score']:.2f} < {threshold})"

            if expected_id in top3_ids and top1["score"] >= threshold:
                recall_at_3 += 1

        print(f"   [{status:20s}] '{query_text[:35]:35s}' | Top1: {top1['id']} ({top1['score']:.3f})")

    avg_embed_lat = sum(embed_latencies) / len(embed_latencies)
    total_queries = len(LABELED_QUERIES)

    print("\n" + "=" * 65)
    print("REAL PINECONE INFERENCE BENCHMARK METRICS SUMMARY")
    print("=" * 65)
    print(f"  Model Name              : multilingual-e5-large")
    print(f"  Dimension               : 1024")
    print(f"  Total Labeled Queries   : {total_queries}")
    print(f"  Top-1 Accuracy          : {(top1_correct / total_queries) * 100.0:.1f}% ({top1_correct}/{total_queries})")
    print(f"  Recall@3 (Valid Queries): {(recall_at_3 / total_valid_queries) * 100.0:.1f}% ({recall_at_3}/{total_valid_queries})")
    print(f"  Incorrect Matches (FP)  : {incorrect_matches}")
    print(f"  Abstention Rate (Noise) : {(correct_abstentions / total_noise_queries) * 100.0:.1f}% ({correct_abstentions}/{total_noise_queries})")
    print(f"  Average Embed Latency   : {avg_embed_lat:.1f} ms (min: {min(embed_latencies):.1f} ms, max: {max(embed_latencies):.1f} ms)")
    print("=" * 65)


if __name__ == "__main__":
    run_real_evaluation()
