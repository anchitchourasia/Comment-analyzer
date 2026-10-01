import os
import sys
import shutil
import hashlib
import json
from datetime import datetime
from pathlib import Path

FILES_TO_BACKUP = [
    "analyzer 4.py",
    "answer_poster.py",
    "live_chat_poller.py",
    "streamlit_app.py",
    "qa_engine.py",
    "groq_service.py",
    "livechat_id_generator.py",
    "qa_data.json",
    "pending_questions.json",
    ".streamlit/secrets.toml",
]

def sha256_file(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()

def create_backup(source_dir: Path, backups_base_dir: Path, milestone: str = "M0") -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backups_base_dir / f"{timestamp}_{milestone}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    manifest = {
        "milestone": milestone,
        "timestamp": timestamp,
        "files": {}
    }
    
    for rel_path_str in FILES_TO_BACKUP:
        src_path = source_dir / rel_path_str
        if src_path.exists() and src_path.is_file():
            dst_path = backup_dir / rel_path_str
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            file_hash = sha256_file(dst_path)
            manifest["files"][rel_path_str] = file_hash

    manifest_path = backup_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        
    return backup_dir

def verify_backup(backup_dir: Path) -> bool:
    manifest_path = backup_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: manifest.json missing in {backup_dir}")
        return False
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    for rel_path_str, expected_hash in manifest.get("files", {}).items():
        file_path = backup_dir / rel_path_str
        if not file_path.exists():
            print(f"Error: Backed up file {rel_path_str} missing in {backup_dir}")
            return False
        actual_hash = sha256_file(file_path)
        if actual_hash != expected_hash:
            print(f"Error: Hash mismatch for {rel_path_str} in {backup_dir}")
            return False
            
    return True

if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    backups_dir = project_root / "backups"
    b_dir = create_backup(project_root, backups_dir, "M0")
    if verify_backup(b_dir):
        print(f"Backup created and verified successfully at: {b_dir.name}")
        sys.exit(0)
    else:
        print("Backup verification failed!")
        sys.exit(1)
