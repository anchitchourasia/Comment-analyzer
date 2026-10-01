import sys
import tempfile
import hashlib
from pathlib import Path

# Add scripts directory to path to import backup and restore
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup
import restore

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def run_test():
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        source_dir = temp_dir / "source"
        backups_dir = temp_dir / "backups"
        restore_dir = temp_dir / "restored"

        source_dir.mkdir(parents=True)
        backups_dir.mkdir(parents=True)
        restore_dir.mkdir(parents=True)

        # Create dummy test files matching backed-up filenames
        test_file_content = {"streamlit_app.py": "print('hello world')", "answer_poster.py": "class Poster: pass"}
        original_hashes = {}
        for filename, content in test_file_content.items():
            file_path = source_dir / filename
            file_path.write_text(content, encoding="utf-8")
            original_hashes[filename] = sha256_file(file_path)

        # Step 1: Perform backup from source_dir
        backup_dir = backup.create_backup(source_dir, backups_dir, "test_M0")
        assert backup.verify_backup(backup_dir), "Backup verification failed in test!"

        # Step 2: Modify source files in source_dir (simulating changes/corruption)
        for filename in test_file_content.keys():
            (source_dir / filename).write_text("corrupted content", encoding="utf-8")

        # Step 3: Perform restore from backup_dir into restore_dir
        assert restore.restore_backup(backup_dir, restore_dir), "Restore failed in test!"

        # Step 4: Verify restored files match original hashes
        for filename, expected_hash in original_hashes.items():
            restored_file = restore_dir / filename
            assert restored_file.exists(), f"Restored file {filename} does not exist!"
            actual_hash = sha256_file(restored_file)
            assert actual_hash == expected_hash, f"Hash mismatch for {filename}! Expected {expected_hash}, got {actual_hash}"

        print("test_restore: all checks passed")

if __name__ == "__main__":
    run_test()
