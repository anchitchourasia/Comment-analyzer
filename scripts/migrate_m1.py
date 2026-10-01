import sys
import json
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend import storage

def migrate_m1(channel_id: str, dry_run: bool = False) -> bool:
    validated_ch = storage.validate_channel_id(channel_id)
    target_dir = storage.get_channel_dir(validated_ch)

    src_qa = BASE_DIR / "qa_data.json"
    src_pending = BASE_DIR / "pending_questions.json"

    dst_qa = target_dir / "qa_data.json"
    dst_pending = target_dir / "pending_questions.json"

    if dst_qa.exists() and dst_qa.stat().st_size > 2:
        print(f"Migration for channel {validated_ch!r} skipped: target file {dst_qa} already exists and is non-empty (idempotent).")
        return True

    print(f"Migrating Q&A and pending data to channel {validated_ch!r} ({target_dir})...")

    # Read and validate source QA
    qa_data = []
    if src_qa.exists():
        try:
            qa_data = json.loads(src_qa.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error reading source QA file {src_qa}: {e}")
            return False

    # Read and validate source Pending
    pending_data = {}
    if src_pending.exists():
        try:
            pending_data = json.loads(src_pending.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error reading source Pending file {src_pending}: {e}")
            return False

    if dry_run:
        print(f"[DRY-RUN] Would write {len(qa_data)} QA records to {dst_qa}")
        print(f"[DRY-RUN] Would write {len(pending_data)} Pending records to {dst_pending}")
        return True

    # Write target files using atomic write
    import qa_engine
    import live_chat_poller

    qa_engine.atomic_write_json(dst_qa, qa_data)
    live_chat_poller.atomic_write_json(dst_pending, pending_data)

    # Verify target files
    try:
        read_qa = json.loads(dst_qa.read_text(encoding="utf-8"))
        read_pending = json.loads(dst_pending.read_text(encoding="utf-8"))
        assert len(read_qa) == len(qa_data)
        assert len(read_pending) == len(pending_data)
    except Exception as e:
        print(f"Migration verification failed: {e}")
        return False

    print(f"Migration to channel {validated_ch!r} completed successfully: {len(qa_data)} Q&A records, {len(pending_data)} pending items.")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy root Q&A data to a specific channel store.")
    parser.add_argument("--channel-id", required=True, help="Verified YouTube Channel ID (e.g., UCxxxxxxxx)")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying files")
    args = parser.parse_args()

    success = migrate_m1(args.channel_id, dry_run=args.dry_run)
    sys.exit(0 if success else 1)
