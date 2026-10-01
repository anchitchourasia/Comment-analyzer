import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
CHANNELS_DIR = DATA_DIR / "channels"

# Valid channel ID regex: alphanumeric, underscores, hyphens, typically starting with UC
CHANNEL_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]+$")

def validate_channel_id(channel_id: str) -> str:
    """Validate that channel_id is a non-empty string without path traversal."""
    if not channel_id or not isinstance(channel_id, str):
        raise ValueError("channel_id must be a non-empty string.")
    ch = channel_id.strip()
    if not CHANNEL_ID_REGEX.match(ch) or ".." in ch or "/" in ch or "\\" in ch:
        raise ValueError(f"Invalid channel_id format or path traversal attempt: {channel_id!r}")
    return ch

def get_channel_dir(channel_id: str) -> Path:
    """Return Path to data/channels/{channel_id}/, ensuring directory exists."""
    ch = validate_channel_id(channel_id)
    ch_dir = CHANNELS_DIR / ch
    ch_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return ch_dir

def get_qa_path(channel_id: str | None = None) -> Path:
    if channel_id:
        return get_channel_dir(channel_id) / "qa_data.json"
    return BASE_DIR / "qa_data.json"

def get_pending_path(channel_id: str | None = None) -> Path:
    if channel_id:
        return get_channel_dir(channel_id) / "pending_questions.json"
    return BASE_DIR / "pending_questions.json"

def get_settings_path(channel_id: str) -> Path:
    return get_channel_dir(channel_id) / "settings.json"

def get_cooldown_path(channel_id: str | None = None) -> Path:
    if channel_id:
        return get_channel_dir(channel_id) / "cooldown.json"
    return BASE_DIR / "cooldown.json"

def get_log_path(channel_id: str | None = None) -> Path:
    if channel_id:
        return get_channel_dir(channel_id) / "posted_log.jsonl"
    return BASE_DIR / "posted_log.jsonl"

def log_posted_message(channel_id: str | None, entry_data: dict):
    """Persist a successfully posted YouTube message to posted_log.jsonl."""
    import json
    log_path = get_log_path(channel_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with interprocess_file_lock(log_path):
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry_data) + "\n")


import os
import time
import threading
from contextlib import contextmanager

_active_process_locks = threading.local()

def _get_active_locks() -> set:
    if not hasattr(_active_process_locks, "locks"):
        _active_process_locks.locks = set()
    return _active_process_locks.locks

@contextmanager
def interprocess_file_lock(file_path: Path | str | None, timeout_seconds: float = 10.0, poll_interval: float = 0.02):
    """
    Atomic cross-process file lock using O_CREAT | O_EXCL.
    Ensures safe read-check-modify-write transactions on disk across separate OS processes.
    """
    if file_path is None:
        yield
        return

    lock_path_str = str(Path(file_path).resolve().with_suffix(".lock"))
    active = _get_active_locks()

    if lock_path_str in active:
        yield
        return

    lock_file = Path(lock_path_str)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    fd = None

    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_RDWR)
            try:
                os.write(fd, f"{os.getpid()}:{time.time()}".encode("utf-8"))
            except OSError:
                pass
            break
        except FileExistsError:
            try:
                mtime = lock_file.stat().st_mtime
                if time.time() - mtime > 15.0:
                    try:
                        lock_file.unlink()
                    except OSError:
                        pass
            except OSError:
                pass

            if time.time() - start_time > timeout_seconds:
                try:
                    lock_file.unlink()
                except OSError:
                    pass
                start_time = time.time()
            time.sleep(poll_interval)

    active.add(lock_path_str)
    try:
        yield
    finally:
        active.discard(lock_path_str)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if lock_file.exists():
                lock_file.unlink()
        except OSError:
            pass

