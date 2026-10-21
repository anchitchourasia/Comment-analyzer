"""Migration and backfill utility for Genuine Multilingual Semantic Q&A.

Backfills vector embeddings for approved Q&A records into the Pinecone semantic index.
- Dry-run mode by default (safe inspection).
- Requires explicit '--apply' flag to perform writes.
- Validates source records and approval status.
- Never deletes or modifies original storage records.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import storage
import backend.semantic_pinecone as semantic_pinecone
from backend.embeddings.factory import get_embedding_provider
from backend.semantic_retriever import preprocess_for_embedding
import qa_engine


def validate_qa_record(record: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate that a record meets the schema and safety requirements."""
    if not isinstance(record, dict):
        return False, "Record is not a dictionary"
    if not record.get("id"):
        return False, "Missing record ID"
    if not str(record.get("normalized_question", "")).strip():
        return False, "Empty or missing normalized_question"
    if not str(record.get("answer_text", "")).strip():
        return False, "Empty or missing answer_text"
    return True, None


def run_migration(
    channel_id: Optional[str] = None,
    dry_run: bool = True,
    batch_size: int = 50,
) -> Dict[str, Any]:
    """Run migration across channels with detailed reporting."""
    provider = get_embedding_provider()
    results = {
        "mode": "DRY-RUN (No writes performed)" if dry_run else "APPLY (Writing to Pinecone)",
        "model_name": provider.model_name,
        "dimension": provider.dimension,
        "channels_scanned": 0,
        "total_records_found": 0,
        "approved_records": 0,
        "draft_records_skipped": 0,
        "invalid_records_skipped": 0,
        "vectors_prepared": 0,
        "vectors_upserted": 0,
        "channel_summaries": [],
    }

    # Discover channels
    channels_dir = Path("data") / "channels"
    channel_ids = []
    if channel_id:
        channel_ids.append(channel_id)
    elif channels_dir.exists():
        for ch_dir in channels_dir.iterdir():
            if ch_dir.is_dir() and ch_dir.name.startswith("UC"):
                channel_ids.append(ch_dir.name)

    if not channel_ids:
        # Check root/session fallback
        channel_ids = ["default"]

    for ch in channel_ids:
        results["channels_scanned"] += 1
        records = qa_engine.load_qa_data(channel_id=ch if ch != "default" else None)
        ch_approved = 0
        ch_drafts = 0
        ch_invalid = 0
        vectors_to_upsert = []

        for rec in records:
            results["total_records_found"] += 1
            valid, err = validate_qa_record(rec)
            if not valid:
                ch_invalid += 1
                results["invalid_records_skipped"] += 1
                continue

            if rec.get("status") != "approved":
                ch_drafts += 1
                results["draft_records_skipped"] += 1
                continue

            ch_approved += 1
            results["approved_records"] += 1

            # Prepare embedding text (canonical question + example phrasings)
            canonical = rec.get("normalized_question", "")
            examples = rec.get("original_question_examples", []) or []
            phrasings = [canonical] + [e for e in examples if e and e != canonical]

            # Generate vector for primary canonical phrasing
            embed_text = preprocess_for_embedding(phrasings[0])
            if hasattr(provider, "embed_text") and "input_type" in provider.embed_text.__code__.co_varnames:
                vector_vals = provider.embed_text(embed_text, input_type="passage")
            else:
                vector_vals = provider.embed_text(embed_text)

            vectors_to_upsert.append({
                "id": rec["id"],
                "values": vector_vals,
                "metadata": {
                    "record_id": rec["id"],
                    "normalized_question": rec["normalized_question"],
                    "status": "approved",
                    "model_name": provider.model_name,
                    "schema_version": "semantic_v1",
                    "channel_id": ch,
                    "example_count": len(phrasings),
                },
            })
            results["vectors_prepared"] += 1

        ch_upserted = 0
        if not dry_run and vectors_to_upsert:
            ch_upserted = semantic_pinecone.upsert_semantic_vectors(
                vectors=vectors_to_upsert,
                channel_id=ch,
                batch_size=batch_size,
            )
            results["vectors_upserted"] += ch_upserted

        results["channel_summaries"].append({
            "channel_id": ch,
            "total_records": len(records),
            "approved": ch_approved,
            "drafts": ch_drafts,
            "invalid": ch_invalid,
            "vectors_prepared": len(vectors_to_upsert),
            "vectors_upserted": ch_upserted if not dry_run else 0,
        })

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Q&A Memory to Semantic Pinecone Index")
    parser.add_argument("--apply", action="store_true", help="Execute remote writes (default is dry-run)")
    parser.add_argument("--channel-id", type=str, default=None, help="Filter to specific channel ID")
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for vector upserts")

    args = parser.parse_args()
    is_dry_run = not args.apply

    print("=" * 60)
    print("Comment-Analyzer: Multilingual Semantic Q&A Migration Tool")
    print("=" * 60)
    if is_dry_run:
        print(">>> RUNNING IN DRY-RUN MODE (No external writes will occur)")
        print(">>> Pass '--apply' to execute actual remote writes.")
    else:
        print(">>> WARNING: APPLY MODE ACTIVE — Remote writes will be executed!")

    summary = run_migration(
        channel_id=args.channel_id,
        dry_run=is_dry_run,
        batch_size=args.batch_size,
    )

    print("\nMigration Results Summary:")
    print(f"  Mode: {summary['mode']}")
    print(f"  Model: {summary['model_name']} ({summary['dimension']} dims)")
    print(f"  Channels Scanned: {summary['channels_scanned']}")
    print(f"  Total Records Found: {summary['total_records_found']}")
    print(f"  Approved Records: {summary['approved_records']}")
    print(f"  Drafts Skipped: {summary['draft_records_skipped']}")
    print(f"  Invalid Skipped: {summary['invalid_records_skipped']}")
    print(f"  Vectors Prepared: {summary['vectors_prepared']}")
    print(f"  Vectors Upserted: {summary['vectors_upserted']}")
    print("-" * 60)
    for ch in summary["channel_summaries"]:
        print(f"  Channel: {ch['channel_id']} | Total: {ch['total_records']} | Approved: {ch['approved']} | Prepared: {ch['vectors_prepared']} | Upserted: {ch['vectors_upserted']}")
    print("=" * 60)
