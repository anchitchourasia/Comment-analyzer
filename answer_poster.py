import json
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

from backend import storage

POST_COOLDOWN_SECONDS = 300
GLOBAL_POST_GAP_SECONDS = 5
MESSAGE_CHAR_LIMIT = 200

_active_posters_lock = threading.Lock()
_active_posters_by_channel = {}

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def get_backend_url():
    import os
    return os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

class AnswerPoster:
    def __init__(self, session_token, channel_id, cooldown_path=None, log_path=None):
        self.session_token = session_token
        self.channel_id = channel_id
        
        if self.channel_id:
            with _active_posters_lock:
                existing = _active_posters_by_channel.get(self.channel_id)
                if existing is not None and existing._worker_thread.is_alive():
                    raise RuntimeError(f"Active AnswerPoster already exists for channel {self.channel_id!r}. Single-writer rule enforced.")
                _active_posters_by_channel[self.channel_id] = self

        self.cooldown_path = Path(cooldown_path) if cooldown_path else storage.get_cooldown_path(self.channel_id)
        self.log_path = Path(log_path) if log_path else storage.get_log_path(self.channel_id)

        self._post_lock = threading.Lock()
        self._last_posted_at = {}  # record id -> wall_clock timestamp (float)
        self._last_post_time = 0.0

        self.last_error = None
        self.last_status = "idle"

        self._queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)

        with self._post_lock:
            self._load_cooldown_locked()
        self._worker_thread.start()

    def _load_cooldown_locked(self):
        if not self.cooldown_path.exists():
            return
        try:
            data = json.loads(self.cooldown_path.read_text(encoding="utf-8"))
            file_per_record = data.get("per_record", {})
            for k, v in file_per_record.items():
                if k not in self._last_posted_at or v > self._last_posted_at[k]:
                    self._last_posted_at[k] = v
            file_last_post = data.get("last_post_time", 0.0)
            if file_last_post > self._last_post_time:
                self._last_post_time = file_last_post
        except Exception:
            pass

    def _save_cooldown_locked(self):
        self._load_cooldown_locked()
        data = {
            "per_record": self._last_posted_at,
            "last_post_time": self._last_post_time
        }
        tmp_file = self.cooldown_path.with_suffix(".tmp")
        try:
            self.cooldown_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_file.replace(self.cooldown_path)
        except Exception:
            pass

    def cooldown_active(self, record_id, cooldown_seconds=None):
        with self._post_lock:
            self._load_cooldown_locked()
            return self._cooldown_active_locked(record_id, cooldown_seconds=cooldown_seconds)

    def _cooldown_active_locked(self, record_id, cooldown_seconds=None):
        last = self._last_posted_at.get(record_id)
        if last is None:
            return False
        c_sec = POST_COOLDOWN_SECONDS if cooldown_seconds is None else max(0, float(cooldown_seconds))
        return (time.time() - last) < c_sec

    def post_answer(self, answer_text, live_chat_id, record_id=None, cooldown_seconds=None):
        with self._post_lock:
            self._load_cooldown_locked()
            if record_id is not None and self._cooldown_active_locked(record_id, cooldown_seconds=cooldown_seconds):
                return False

            now = time.time()
            if record_id is not None:
                self._last_posted_at[record_id] = now
                self._save_cooldown_locked()

            message = str(answer_text)[:MESSAGE_CHAR_LIMIT]
            self._queue.put((message, live_chat_id, record_id))
            return True

    def clear_queue(self):
        with self._post_lock:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    break

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            message, live_chat_id, record_id = item
            try:
                with self._post_lock:
                    last_post = self._last_post_time

                gap_remaining = GLOBAL_POST_GAP_SECONDS - (time.time() - last_post)
                if gap_remaining > 0:
                    time.sleep(gap_remaining)

                # Post via FastAPI Backend
                if self.session_token and self.channel_id:
                    backend_url = get_backend_url()
                    res = requests.post(
                        f"{backend_url}/api/channel/{self.channel_id}/post",
                        headers={"x-session-token": self.session_token},
                        json={"answer_text": message, "live_chat_id": live_chat_id, "record_id": record_id}
                    )
                    if res.status_code != 200:
                        raise Exception(f"Backend API error: {res.text}")

                now = time.time()
                with self._post_lock:
                    self._last_post_time = now
                    self.last_error = None
                    self.last_status = "ok"
                    self._save_cooldown_locked()

                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as file:
                    file.write(json.dumps({
                        "at": _now_iso(),
                        "record_id": record_id,
                        "text": message,
                    }) + "\n")
            except Exception as e:
                with self._post_lock:
                    self.last_error = str(e)
                    self.last_status = "error"
                sys.stderr.write(f"AnswerPoster worker error: {e}\n")
            finally:
                self._queue.task_done()

    def wait_for_queue(self):
        self._queue.join()

    def stop(self, clear_queue=True):
        if clear_queue:
            self.clear_queue()
        self._stop_event.set()
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)
        if self.channel_id:
            with _active_posters_lock:
                if _active_posters_by_channel.get(self.channel_id) is self:
                    del _active_posters_by_channel[self.channel_id]


def is_configured(session_token):
    """True if we have a session token."""
    return bool(session_token)

def get_poster(session_token, channel_id):
    if not session_token or not channel_id:
        return None
    poster = AnswerPoster(session_token, channel_id)
    poster.own_channel_id = channel_id
    return poster
