import sys
import shutil
import hashlib
import json
from pathlib import Path

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def restore_backup(backup_dir: Path, target_dir: Path) -> bool:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: manifest.json missing in {backup_dir}")
        return False

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for rel_path_str, expected_hash in manifest.get("files", {}).items():
        src_path = backup_dir / rel_path_str
        if not src_path.exists():
            print(f"Error: file {rel_path_str} missing in backup {backup_dir}")
            return False
        
        dst_path = target_dir / rel_path_str
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)

        actual_hash = sha256_file(dst_path)
        if actual_hash != expected_hash:
            print(f"Error: restored file {rel_path_str} hash mismatch")
            return False

    return True

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python restore.py <path_to_backup_dir> [target_dir]")
        sys.exit(1)

    backup_dir = Path(sys.argv[1]).resolve()
    target_dir = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent

    if restore_backup(backup_dir, target_dir):
        print(f"Restore completed successfully to {target_dir}")
        sys.exit(0)
    else:
        print("Restore failed!")
        sys.exit(1)
