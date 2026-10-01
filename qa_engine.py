"""Q&A memory: v2 schema, thread-safe, session-temporary.

Storage is IN-MEMORY only, scoped to the current assistant session:
it starts empty when the assistant starts and is wiped when the poller
stops, the stream ends, or videos switch. Nothing persists between
streams. Tests redirect storage to a real file via QA_FILE to exercise
the exact file save/load/corrupt-parking logic.

One JSON record per approved question:
    id, normalized_question, original_question_examples, answer_text,
    status ("approved" | "draft"), auto_reply, usage_count,
    created_at, updated_at, last_used_at

Only "approved" records are returned by find_best_answer — that is what
gates everything the poller does.
"""

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend import storage

QA_FILE = None  # explicit file override (tests); None = in-memory session or channel path

# Legacy root file (pre-session data): read-only from now on. The Memory
# Editor's explicit import button copies out of it; nothing ever writes
# or deletes it. A snapshot lives in legacy_backup/.
LEGACY_QA_FILE = Path(__file__).resolve().parent / "qa_data.json"

# In-memory session store: starts empty, cleared on stop / stream end /
# video switch. All access under QA_LOCK.
_session_records = []

# One lock for the memory file: the poller thread and the Streamlit UI
# both mutate it. RLock so public functions can call each other freely.
QA_LOCK = threading.RLock()

MAX_EXAMPLES = 5  # original viewer phrasings kept per entry


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _new_id():
    return "q_" + uuid.uuid4().hex[:8]


# --- text matching (Phase 1 logic, unchanged) --------------------------------


def normalize_text(text):
    text = str(text).lower()
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_STOP_WORDS = {
    "a", "an", "and", "are", "is", "the", "to", "of", "in", "on", "for",
    "do", "does", "you", "your", "i", "we", "it", "what", "which", "who",
    "how", "where", "when", "why", "please", "can", "could",
}


def tokenize(text):
    return {
        word
        for word in normalize_text(text).split()
        if word not in _STOP_WORDS
    }


def calculate_score(question_one, question_two):
    """Jaccard overlap of the two token sets. Phase 1, unchanged.

    ponytail: purely lexical — "camera" != "cameras", order ignored.
    Swap the body (not the signature) for semantic scoring later.
    """
    words_one = tokenize(question_one)
    words_two = tokenize(question_two)

    if not words_one or not words_two:
        return 0.0

    return len(words_one & words_two) / len(words_one | words_two)


# --- storage ------------------------------------------------------------------


def atomic_write_json(path, data):
    """Write-then-rename so a crash mid-write can't corrupt the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


# --- session memory ---------------------------------------------------------------


def reset_session_memory():
    """Drop all temporary Q&A. start_assistant calls this so a new stream
    begins empty; the poller calls it on stop, stream end, and video
    switch. Does not touch any file."""
    with QA_LOCK:
        _session_records.clear()


def _to_v2(item):
    """Coerce one loaded item to the v2 schema; None if unusable.

    Accepts Phase 1 {"question": ..., "answer": ...} pairs unchanged,
    so an old qa_data.json migrates on first load.
    """
    if not isinstance(item, dict):
        return None

    examples = item.get("original_question_examples")
    if isinstance(examples, list):
        examples = [str(e).strip() for e in examples if str(e).strip()]
    else:
        examples = []

    # Phase 1 migration: the raw question becomes the first example
    if not examples and item.get("question"):
        examples = [str(item["question"]).strip()]

    answer = str(item.get("answer_text", item.get("answer", ""))).strip()
    normalized = str(item.get("normalized_question") or "").strip()

    if not normalized and examples:
        normalized = normalize_text(examples[0])

    if not normalized or not answer:
        return None

    status = item.get("status")
    if status not in ("approved", "draft"):
        status = "approved"

    return {
        "id": str(item.get("id") or _new_id()),
        "normalized_question": normalized,
        "original_question_examples": examples[:MAX_EXAMPLES],
        "answer_text": answer,
        "status": status,
        "auto_reply": bool(item.get("auto_reply", False)),
        "usage_count": int(item.get("usage_count", 0) or 0),
        "created_at": item.get("created_at") or now_iso(),
        "updated_at": item.get("updated_at") or item.get("created_at") or now_iso(),
        "last_used_at": item.get("last_used_at"),
    }


def load_qa_data(channel_id=None):
    with QA_LOCK:
        target_file = QA_FILE if QA_FILE is not None else (storage.get_qa_path(channel_id) if channel_id else None)
        if target_file is not None:
            if not target_file.exists():
                atomic_write_json(target_file, [])
                return []

            try:
                raw = json.loads(target_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                corrupt = target_file.with_name(
                    f"{target_file.name}.corrupt-{now_iso().replace(':', '')}"
                )
                try:
                    os.replace(target_file, corrupt)
                except OSError:
                    pass
                return []

            if not isinstance(raw, list):
                return []

            return [record for record in (_to_v2(item) for item in raw) if record]

        return list(_session_records)


def save_qa_data(data, channel_id=None):
    with QA_LOCK:
        records = [record for record in (_to_v2(item) for item in data) if record]
        target_file = QA_FILE if QA_FILE is not None else (storage.get_qa_path(channel_id) if channel_id else None)
        if target_file is not None:
            atomic_write_json(target_file, records)
        else:
            _session_records[:] = records
        return records



def _remember_example(record, question):
    """Keep the freshest raw phrasings, most recent first, capped."""
    examples = record["original_question_examples"]
    cleaned = str(question).strip()
    if cleaned and cleaned not in examples:
        examples.insert(0, cleaned)
        del examples[MAX_EXAMPLES:]


# --- public operations ----------------------------------------------------------


def add_question_answer(question, answer, auto_reply=False,
                        status="approved", qa_data=None, channel_id=None):
    """Create or update (dedup by normalized question) one memory record
    in the current session's temporary memory or channel store."""
    normalized = normalize_text(question)
    clean_answer = str(answer).strip()

    if not normalized:
        raise ValueError("Question cannot be empty.")
    if not clean_answer:
        raise ValueError("Answer cannot be empty.")
    if status not in ("approved", "draft"):
        raise ValueError("status must be 'approved' or 'draft'.")

    with QA_LOCK:
        data = qa_data if qa_data is not None else load_qa_data(channel_id=channel_id)

        for record in data:
            if record["normalized_question"] == normalized:
                record["answer_text"] = clean_answer
                record["status"] = status
                record["auto_reply"] = bool(auto_reply)
                record["updated_at"] = now_iso()
                _remember_example(record, question)
                save_qa_data(data, channel_id=channel_id)
                return record

        record = {
            "id": _new_id(),
            "normalized_question": normalized,
            "original_question_examples": [str(question).strip()],
            "answer_text": clean_answer,
            "status": status,
            "auto_reply": bool(auto_reply),
            "usage_count": 0,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "last_used_at": None,
        }
        data.append(record)
        save_qa_data(data, channel_id=channel_id)
        return record


def mark_used(record_id, channel_id=None):
    """Bump usage_count / last_used_at after an answer served a viewer."""
    with QA_LOCK:
        data = load_qa_data(channel_id=channel_id)
        for record in data:
            if record["id"] == record_id:
                record["usage_count"] += 1
                record["last_used_at"] = now_iso()
                save_qa_data(data, channel_id=channel_id)
                return record
    return None


def delete_record(record_id, channel_id=None):
    with QA_LOCK:
        data = load_qa_data(channel_id=channel_id)
        remaining = [record for record in data if record["id"] != record_id]
        if len(remaining) != len(data):
            save_qa_data(remaining, channel_id=channel_id)
            return True
    return False



def import_legacy_qa(channel_id=None):
    """Explicit one-click import of the legacy root qa_data.json into the
    specified channel store or session memory. Read-only on legacy file."""
    try:
        raw = json.loads(LEGACY_QA_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(raw, list):
        return 0

    imported = 0
    for item in raw:
        record = _to_v2(item)
        if not record:
            continue
        example = (
            record["original_question_examples"]
            or [record["normalized_question"]]
        )[0]
        add_question_answer(
            example,
            record["answer_text"],
            auto_reply=record["auto_reply"],
            status=record["status"],
            channel_id=channel_id,
        )
        imported += 1
    return imported



def find_best_answer(question, qa_data=None, include_drafts=False, channel_id=None):
    """Best (record, score) for the question; (None, 0.0) if none.

    Filters to status == "approved" unless include_drafts — drafts never
    reach viewers because nothing downstream ever posts them.
    """
    if qa_data is None:
        qa_data = load_qa_data(channel_id=channel_id)


    normalized = normalize_text(question)
    if not normalized:
        return None, 0.0

    if not include_drafts:
        qa_data = [r for r in qa_data if r.get("status") == "approved"]

    best_match = None
    best_score = 0.0

    for record in qa_data:
        stored = record.get("normalized_question", "")

        if normalized == stored:
            return record, 1.0

        score = calculate_score(normalized, stored)
        if score > best_score:
            best_match = record
            best_score = score

    return best_match, best_score
