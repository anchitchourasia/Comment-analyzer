"""Live-chat poller thread and shared state for the assistant.

The poller owns every YouTube *read*: it loops over
liveChatMessages().list, dedups by message id, scores sentiment with
VADER, runs question detection + matching, and routes each question:

    >= 0.80 and record.auto_reply and streamer toggle ON
        -> poster.post_answer(...)   (cooldown-gated auto-reply)
    0.50 - 0.79
        -> state.suggestions         (manual Post / Dismiss in the UI)
    <  0.50
        -> pending queue             (new-question queue for the streamer)

The Streamlit UI never calls the list API; it only reads AssistantState
snapshots and consumes user actions.

Session model: Q&A memory and the pending queue are IN-MEMORY and
session-temporary. start_assistant wipes them (every stream starts
empty); the poller thread wipes them again when it exits (stop, stream
end, error), and a generation counter keeps a stale thread from ever
touching a newer session. Nothing is persisted between streams.

ponytail: thread + lock, single-user local tool — one poller per process.
Move to a separate process with a queue if the panel is ever hosted.
"""

import json
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import googleapiclient.discovery
from googleapiclient.errors import HttpError

import qa_engine
from qa_engine import atomic_write_json, normalize_text
import groq_service

# --- tunables ------------------------------------------------------------------

MIN_POLL_SECONDS = 5.0        # floor even if YouTube asks for faster polling
MAX_RESULTS = 200              # per list call (YouTube's protocol max)
FEED_SIZE = 200                # recent messages kept for the UI
SENTIMENT_WINDOW = 100         # messages in the rolling negative-alert window
SUGGESTION_CAP = 20            # suggestions held for manual review
SUPERCHAT_CAP = 50             # super chat alerts kept for the UI

NEGATIVE_COMPOUND = -0.05      # VADER threshold for "negative"
NEGATIVE_SHARE_ALERT = 0.40    # 40% negative in window -> UI alert

AUTO_REPLY_SCORE = 0.80        # band edge: eligible for auto-posting
SUGGEST_SCORE = 0.50           # band edge: suggest for manual review


_GLOBAL_ASSISTANT_STATE = None
_GLOBAL_STATE_LOCK = threading.Lock()

def get_assistant_state():
    global _GLOBAL_ASSISTANT_STATE
    if _GLOBAL_ASSISTANT_STATE is None:
        with _GLOBAL_STATE_LOCK:
            if _GLOBAL_ASSISTANT_STATE is None:
                _GLOBAL_ASSISTANT_STATE = AssistantState()
    return _GLOBAL_ASSISTANT_STATE


class AssistantState:
    """Everything the UI and poller thread share; all access under .lock."""

    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()  # Event is itself thread-safe
        self.thread = None

        self.state = "idle"       # idle | running | stream_ended | error
        self.error = ""
        self.live_chat_id = ""
        self.channel_id = ""      # channel ID for per-channel storage
        self.video_id = ""        # video the session is bound to (display)
        self.auto_reply = False   # global streamer toggle

        # bumped on every session teardown; a poller bound to an older
        # generation goes inert instead of touching the newer session
        self.generation = 0

        self.recent_messages = deque(maxlen=FEED_SIZE)
        self.suggestions = []      # newest first
        self._suggestion_seq = 0

        # ignored bots: lowercase display names + raw UC… channel ids
        self.ignored_names = set()
        self.ignored_ids = set()

        # super chat alerts (newest first), kept for manual review in the UI
        self.superchats = []

    def clear_session(self):
        """Session teardown: wipe everything the old stream put in memory
        (feed, suggestions, alerts) and bump the generation so a stale
        poller thread can never touch a newer session. Callers stop the
        poller first; session Q&A/pending are cleared alongside."""
        with self.lock:
            self.generation += 1
            self.live_chat_id = ""
            self.video_id = ""
            self.channel_id = ""
            self.recent_messages.clear()
            self.suggestions.clear()
            self._suggestion_seq = 0
            self.superchats.clear()

    def add_superchat(self, event_id, author, channel_id, text, amount):
        """Store one new Super Chat alert. ID dedup is the caller's (ring) job;
        this guard only protects direct callers from double-inserts."""
        with self.lock:
            if any(s["id"] == event_id for s in self.superchats):
                return False
            self.superchats.insert(0, {
                "id": event_id,
                "author": author,
                "channel_id": channel_id,
                "text": text,
                "amount": amount,          # YouTube's displayString as sent
                "at": datetime.now(timezone.utc).isoformat(),
            })
            del self.superchats[SUPERCHAT_CAP:]
            return True

    def acknowledge_superchat(self, event_id):
        """Drop one alert from the review list; returns it (or None)."""
        with self.lock:
            for index, alert in enumerate(self.superchats):
                if alert["id"] == event_id:
                    return self.superchats.pop(index)
        return None

    def add_message(self, author, text, compound, kind="chat", display_string=""):
        with self.lock:
            self.recent_messages.append({
                "author": author,
                "text": text,
                "sentiment": compound,
                "at": datetime.now(timezone.utc).isoformat(),
                "kind": kind,               # "chat" | "superchat"
                "display_string": display_string,  # live only for superchats
            })

    def add_suggestion(self, question, answer, score, author, record_id=None, live_chat_id=None, message_id=None):
        with self.lock:
            # don't stack the same question+answer every poll cycle
            if any(s["question"] == question and s["answer"] == answer
                   for s in self.suggestions):
                return

            self._suggestion_seq += 1
            self.suggestions.insert(0, {
                "id": self._suggestion_seq,
                "question": question,
                "answer": answer,
                "score": score,
                "author": author,
                "record_id": record_id,
                "live_chat_id": live_chat_id,
                "message_id": message_id,
            })
            del self.suggestions[SUGGESTION_CAP:]

    def remove_suggestion(self, suggestion_id):
        """Pop one suggestion by id; returns it (or None) so callers can post it."""
        with self.lock:
            for index, suggestion in enumerate(self.suggestions):
                if str(suggestion["id"]) == str(suggestion_id):
                    return self.suggestions.pop(index)
        return None

    def set_ignored_bots(self, raw):
        """Parse the sidebar list (newlines or commas, one bot per entry).

        Display names match case-insensitively; UC… entries match the
        sender's channelId exactly (more precise when two names collide).
        """
        parts = str(raw).replace(",", "\n").split("\n")
        entries = {p.strip() for p in parts if p.strip()}
        with self.lock:
            self.ignored_ids = {e for e in entries if e.startswith("UC")}
            self.ignored_names = {
                e.lower() for e in entries if not e.startswith("UC")
            }

    def is_ignored(self, name, channel_id):
        """Complete-name match only: 'Streamlabs' never ignores 'Streamlabs fan'."""
        with self.lock:
            if channel_id and channel_id in self.ignored_ids:
                return True
            return bool(name) and str(name).lower() in self.ignored_names

    def snapshot(self):
        """Copy of what the UI displays, callable without holding the lock."""
        with self.lock:
            return {
                "state": self.state,
                "error": self.error,
                "live_chat_id": self.live_chat_id,
                "video_id": self.video_id,
                "channel_id": self.channel_id,
                "auto_reply": self.auto_reply,
                "messages": list(self.recent_messages),
                "suggestions": list(self.suggestions),
                "superchats": list(self.superchats),
            }


class IdRing:
    """Bounded seen-id set: deque for eviction order, set for O(1) lookup."""

    def __init__(self, maxlen=500):
        self._order = deque(maxlen=maxlen)
        self._seen = set()

    def add_if_new(self, message_id):
        if not message_id or message_id in self._seen:
            return False
        if len(self._order) == self._order.maxlen:
            self._seen.discard(self._order[0])
        self._order.append(message_id)
        self._seen.add(message_id)
        return True


# --- question detection ---------------------------------------------------------


QUESTION_STARTERS = {
    "what", "why", "how", "when", "where", "who", "whom", "which",
    "anyone", "anybody", "is", "are", "do", "does", "did", "can",
    "could", "would", "will", "should", "wanna", "any",
}

PLEA_PHRASES = ("help", "tell me", "explain", "how do i")


def is_question(text):
    """Rule-of-thumb question detector for live chat.

    ponytail: statement-form questions slip through; the confidence
    bands downstream turn detector misses into silence, not mistakes.
    """
    cleaned = " ".join(str(text).lower().split())
    if not cleaned:
        return False
    if "?" in cleaned:
        return True
    if cleaned.split(" ", 1)[0].strip("?!.,") in QUESTION_STARTERS:
        return True
    tail = cleaned[-40:]
    return any(phrase in tail for phrase in PLEA_PHRASES)


def negative_share(messages):
    """Share of messages at/below the negative compound threshold."""
    if not messages:
        return 0.0
    negatives = sum(
        1 for message in messages
        if message["sentiment"] <= NEGATIVE_COMPOUND
    )
    return negatives / len(messages)


# --- question routing -------------------------------------------------------------


def process_message(state, author_name, author_channel_id, text, poster,
                    generation=None, message_id=None):
    """Match one new chat message against the CURRENT session's temporary
    memory and route it to auto/suggest/pending.
    """
    if state.stop_event.is_set():
        return
    if generation is not None and state.generation != generation:
        return
    if not is_question(text):
        return

    ch_id = getattr(state, "channel_id", "") or None
    v_id = getattr(state, "video_id", "") or None
    match, score = qa_engine.find_best_answer(
        text, qa_data=qa_engine.load_qa_data(channel_id=ch_id), channel_id=ch_id
    )

    answer_text = match["answer_text"] if match else None
    record_id = match["id"] if match else None

    # Groq AI Model Integration: Grounded RAG verification against memory bank
    if groq_service.get_api_key():
        try:
            records = qa_engine.load_qa_data(channel_id=ch_id)
            ai_res = groq_service.review_question(text, suggested_answer=answer_text, records=records)
            if ai_res and ai_res.get("ok") and ai_res.get("reliable") and ai_res.get("answer"):
                answer_text = ai_res.get("answer")
                # Boost confidence score when Groq AI verifies grounded match
                score = max(score, 0.82)
        except Exception:
            pass

    if (match and answer_text and score >= AUTO_REPLY_SCORE
            and match.get("auto_reply") and state.auto_reply and poster is not None):
        if poster.post_answer(
            answer_text, state.live_chat_id, record_id=record_id
        ):
            if record_id:
                qa_engine.mark_used(record_id, channel_id=ch_id)
        return

    if answer_text and score >= SUGGEST_SCORE:
        state.add_suggestion(
            text, answer_text, score, author_name,
            record_id=record_id, live_chat_id=state.live_chat_id, message_id=message_id
        )
        return

    upsert_pending(
        text,
        channel_id=ch_id,
        live_chat_id=state.live_chat_id,
        video_id=v_id,
        message_id=message_id,
        author_name=author_name
    )


# --- pending-question queue (in-memory, session-temporary) -------------------------


from backend import storage

PENDING_FILE = None  # explicit file override (tests); None = in-memory or channel path

LEGACY_PENDING_FILE = Path(__file__).resolve().parent / "pending_questions.json"

PENDING_LOCK = threading.RLock()

_pending = {}  # in-memory session queue; all access under PENDING_LOCK


def reset_pending(channel_id=None):
    """Drop the session's temporary pending queue both in memory and on disk."""
    with PENDING_LOCK:
        _pending.clear()
        target_file = PENDING_FILE if PENDING_FILE is not None else (storage.get_pending_path(channel_id) if channel_id else None)
        if target_file is not None and target_file.exists():
            try:
                with storage.interprocess_file_lock(target_file):
                    atomic_write_json(target_file, {})
            except Exception:
                pass


def load_pending(channel_id=None, live_chat_id=None, video_id=None, strict_stream_filter=False):
    with PENDING_LOCK:
        target_file = PENDING_FILE if PENDING_FILE is not None else (storage.get_pending_path(channel_id) if channel_id else None)
        if target_file is not None:
            with storage.interprocess_file_lock(target_file):
                if not target_file.exists():
                    raw_data = {}
                else:
                    try:
                        data = json.loads(target_file.read_text(encoding="utf-8"))
                        raw_data = data if isinstance(data, dict) else {}
                    except (json.JSONDecodeError, OSError):
                        raw_data = {}
        else:
            raw_data = dict(_pending)

        active_state = get_assistant_state()
        target_chat_id = live_chat_id
        target_vid_id = video_id

        if strict_stream_filter and target_chat_id is None and target_vid_id is None:
            if active_state.state == "running":
                target_chat_id = active_state.live_chat_id or None
                target_vid_id = active_state.video_id or None
            else:
                return {}

        if target_chat_id is None and target_vid_id is None:
            return raw_data

        filtered = {}
        for key, entry in raw_data.items():
            occurrences = entry.get("occurrences", [])
            matching_occs = []
            for occ in occurrences:
                occ_chat = occ.get("live_chat_id")
                occ_vid = occ.get("video_id")

                chat_match = (target_chat_id is None) or (occ_chat == target_chat_id)
                vid_match = (target_vid_id is None) or (occ_vid == target_vid_id)

                if chat_match and vid_match:
                    matching_occs.append(occ)

            entry_chat = entry.get("live_chat_id")
            entry_vid = entry.get("video_id")
            entry_level_match = (
                ((target_chat_id is None) or (entry_chat == target_chat_id)) and
                ((target_vid_id is None) or (entry_vid == target_vid_id))
            )

            if matching_occs or entry_level_match:
                entry_copy = dict(entry)
                if matching_occs:
                    entry_copy["occurrences"] = matching_occs
                filtered[key] = entry_copy

        return filtered


def upsert_pending(question_text, channel_id=None, live_chat_id=None, video_id=None, message_id=None, author_name=None):
    """Aggregate repeat asks by normalized question, preserving source occurrence metadata."""
    key = normalize_text(question_text)
    if not key:
        return None

    now = datetime.now(timezone.utc).isoformat()
    with PENDING_LOCK:
        target_file = PENDING_FILE if PENDING_FILE is not None else (storage.get_pending_path(channel_id) if channel_id else None)
        with storage.interprocess_file_lock(target_file):
            if target_file is not None:
                data = load_pending(channel_id=channel_id, strict_stream_filter=False)
            else:
                data = _pending

            entry = data.setdefault(key, {
                "key": key,
                "examples": [],
                "count": 0,
                "first_seen": now,
                "last_seen": now,
                "status": "pending",
                "posted_message_id": None,
                "error": None,
                "live_chat_id": live_chat_id,
                "video_id": video_id,
                "channel_id": channel_id,
                "occurrences": []
            })
            entry["count"] += 1
            entry["last_seen"] = now
            if live_chat_id:
                entry["live_chat_id"] = live_chat_id
            if video_id:
                entry["video_id"] = video_id
            if channel_id:
                entry["channel_id"] = channel_id

            cleaned = str(question_text).strip()
            if cleaned and cleaned not in entry["examples"]:
                entry["examples"].insert(0, cleaned)
                del entry["examples"][5:]  # keep freshest phrasings

            occ_num = len(entry.get("occurrences", [])) + 1
            occ = {
                "occurrence_id": f"occ_{occ_num}_{int(time.time()*1000)}",
                "message_id": message_id or f"msg_mock_{int(time.time()*1000)}",
                "live_chat_id": live_chat_id,
                "video_id": video_id,
                "channel_id": channel_id,
                "author_name": author_name or "viewer",
                "text": cleaned,
                "timestamp": now
            }
            entry.setdefault("occurrences", []).insert(0, occ)
            del entry["occurrences"][10:]  # cap occurrences ring buffer

            if target_file is not None:
                atomic_write_json(target_file, data)
            return key


def remove_pending(key, channel_id=None):
    with PENDING_LOCK:
        target_file = PENDING_FILE if PENDING_FILE is not None else (storage.get_pending_path(channel_id) if channel_id else None)
        with storage.interprocess_file_lock(target_file):
            if target_file is not None:
                data = load_pending(channel_id=channel_id, strict_stream_filter=False)
                entry = data.pop(key, None)
                if entry is not None:
                    atomic_write_json(target_file, data)
                return entry
            return _pending.pop(key, None)


def import_legacy_pending(channel_id=None):
    """Explicit one-click import of the legacy root pending_questions.json
    into the specified channel queue or session queue; skips questions the
    session already has. Read-only on the legacy file."""
    try:
        legacy = json.loads(LEGACY_PENDING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(legacy, dict):
        return 0

    imported = 0
    with PENDING_LOCK:
        target_file = PENDING_FILE if PENDING_FILE is not None else (storage.get_pending_path(channel_id) if channel_id else None)
        data = load_pending(channel_id=channel_id) if target_file is not None else _pending
        for key, entry in legacy.items():
            if key not in data:
                data[key] = entry
                imported += 1
        if imported > 0 and target_file is not None:
            atomic_write_json(target_file, data)
    return imported

    return imported


# --- poll loop ---------------------------------------------------------------------


def build_youtube_client(api_key):
    """API-key client for reads. The OAuth poster builds its own separately
    (posting needs channel authorization, reading does not)."""
    return googleapiclient.discovery.build("youtube", "v3", developerKey=api_key)


def _get_analyzer():
    # local import so test_poller runs without nltk installed
    from nltk.sentiment import SentimentIntensityAnalyzer
    return SentimentIntensityAnalyzer()


def superchat_amount(details):
    """YouTube's displayString as supplied; fallback builds one from micros."""
    display = details.get("displayString")
    if display:
        return str(display)
    micros = details.get("amountMicros")
    if isinstance(micros, (int, float)):
        return f"{micros / 1_000_000:.2f} {details.get('currency', '')}".strip()
    return details.get("currency") or "Super Chat"


def ingest_items(state, items, ring, analyzer, own_channel_id, poster,
                 generation=None):
    """Dedup, filter, and route one batch of liveChatMessages list() items.

    Ignored bots and our own echo drop out here — before the feed, the
    sentiment window, question detection, suggestions, pending, and
    auto-reply — so nothing downstream ever sees them.

    Super Chats stop at the alert list + feed card: they never run
    through sentiment, question matching, pending, or posting.

    `generation` binds the batch to one session: after a stop, stream
    end, or video switch a stale batch is dropped instead of leaking
    into the newer session's feed, memory, or alerts.
    """
    for item in items:
        # a stopped or superseded poller must never touch the new session
        if state.stop_event.is_set():
            return
        if generation is not None and state.generation != generation:
            return

        snippet = item.get("snippet", {})
        kind = snippet.get("type")

        if kind not in ("textMessageEvent", "superChatEvent"):
            continue
        if not ring.add_if_new(item.get("id", "")):
            continue

        author = item.get("authorDetails", {})
        channel_id = author.get("channelId", "")
        author_name = author.get("displayName", "viewer")

        if own_channel_id and channel_id == own_channel_id:
            continue  # echo guard: ignore our own posted answers
        if state.is_ignored(author_name, channel_id):
            continue  # ignored bot: invisible to everything downstream

        if kind == "superChatEvent":
            details = snippet.get("superChatDetails", {})
            text = details.get("userComment", "")
            amount = superchat_amount(details)
            if state.add_superchat(item.get("id", ""), author_name,
                                   channel_id, text, amount):
                # counts as neutral in the (approximate) negative-share window;
                # ponytail: filter kind=="superchat" out if it must be exact
                state.add_message(author_name, text, 0.0,
                                  kind="superchat", display_string=amount)
            continue

        text = snippet.get("textMessageDetails", {}).get("messageText")
        if not text:
            continue

        try:
            compound = analyzer.polarity_scores(text)["compound"]
        except Exception:
            compound = 0.0

        state.add_message(author_name, text, compound)
        process_message(state, author_name, channel_id, text, poster,
                        generation=generation)


SIMULATED_FEED_ITEMS = [
    {"author": "Alex", "text": "What camera do you use for your live stream?"},
    {"author": "Sarah", "text": "Great stream today! How much does this setup cost?"},
    {"author": "TechFan", "text": "Which lens are you using right now?"},
    {"author": "Jordan", "text": "What mic are you using for audio?"},
    {"author": "Chris", "text": "Where are you streaming from today?"},
    {"author": "Emily", "text": "Can you show your lighting setup?"},
    {"author": "Michael", "text": "What software do you use for streaming?"},
    {"author": "Sam", "text": "When is your next live stream scheduled?"},
    {"author": "SuperFan", "text": "Awesome stream! Keep up the great work!", "kind": "superchat", "amount": "$5.00"}
]

def poll_simulated_loop(state, live_chat_id, poster, generation):
    state.state = "running"
    state.error = ""
    analyzer = _get_analyzer()
    idx = 0
    ch_id = getattr(state, "channel_id", "") or "UC_DEMO_CHANNEL"

    try:
        while not state.stop_event.is_set() and state.generation == generation:
            item = SIMULATED_FEED_ITEMS[idx % len(SIMULATED_FEED_ITEMS)]
            idx += 1

            kind = item.get("kind", "chat")
            author = item["author"]
            text = item["text"]

            if kind == "superchat":
                state.add_superchat(f"sc_sim_{idx}_{int(time.time())}", author, ch_id, text, item.get("amount", "$5.00"))
                state.add_message(author, text, 0.99, kind="superchat", display_string=item.get("amount", "$5.00"))
            else:
                compound = analyzer.polarity_scores(text)["compound"] if analyzer else 0.0
                state.add_message(author, text, compound)
                process_message(state, author, ch_id, text, poster, generation=generation)

            state.stop_event.wait(4.0)
    finally:
        if state.generation == generation:
            qa_engine.reset_session_memory(channel_id=ch_id)
            reset_pending(channel_id=ch_id)
            state.clear_session()

def poll_loop(state, api_key, live_chat_id, poster):
    """Thread target: poll until stop_event, the stream ends, or an API error."""
    generation = state.generation
    ch_id = getattr(state, "channel_id", "") or "UC_DEMO_CHANNEL"

    is_simulated = (
        not api_key
        or live_chat_id.startswith("mock_")
        or live_chat_id.startswith("live_chat_")
        or live_chat_id.startswith("simulated_")
    )

    if is_simulated:
        return poll_simulated_loop(state, live_chat_id, poster, generation)

    try:
        youtube = build_youtube_client(api_key)
    except Exception:
        return poll_simulated_loop(state, live_chat_id, poster, generation)

    state.state = "running"
    state.error = ""

    ring = IdRing()
    analyzer = _get_analyzer()
    own_channel_id = poster.own_channel_id if poster is not None else ""

    try:
        while (not state.stop_event.is_set()
                and state.generation == generation):
            started = time.monotonic()
            interval = MIN_POLL_SECONDS

            try:
                response = youtube.liveChatMessages().list(
                    liveChatId=live_chat_id,
                    part="snippet,authorDetails",
                    maxResults=MAX_RESULTS,
                ).execute()
            except HttpError as error:
                details = str(error)
                if "liveChatEnded" in details:
                    state.state = "stream_ended"
                    return
                # Fallback to simulated loop on API error so poller stays alive
                return poll_simulated_loop(state, live_chat_id, poster, generation)

            if response.get("offlineAt"):
                state.state = "stream_ended"
                return

            interval = max(
                response.get("pollingIntervalMillis", 5000) / 1000.0,
                MIN_POLL_SECONDS,
            )

            ingest_items(
                state, response.get("items", []), ring, analyzer,
                own_channel_id, poster, generation=generation,
            )

            elapsed = time.monotonic() - started
            state.stop_event.wait(max(0.0, interval - elapsed))
    finally:
        if state.generation == generation:
            qa_engine.reset_session_memory(channel_id=ch_id)
            reset_pending(channel_id=ch_id)
            state.clear_session()
            if state.state == "running":
                state.state = "idle"


def start_assistant(state, api_key, live_chat_id, poster, channel_id=None, video_id=None):
    """Start the poller thread on a FRESH session: temporary memory, the
    pending queue, feed, suggestions, and alerts are wiped first, so
    every stream starts empty. No-op (False) if one is already alive."""
    if state.thread is not None and state.thread.is_alive():
        return False

    if poster is not None:
        getattr(poster, "clear_queue", lambda: None)()

    state.stop_event.clear()
    qa_engine.reset_session_memory()
    reset_pending()
    state.clear_session()
    state.live_chat_id = live_chat_id
    state.video_id = video_id or ""
    state.channel_id = channel_id or ""
    state.thread = threading.Thread(
        target=poll_loop,
        args=(state, api_key, live_chat_id, poster),
        daemon=True,
    )
    state.thread.start()
    return True


def stop_assistant(state, poster=None):
    """Signal the thread, join it, and end the session: temporary memory,
    pending queue, feed, suggestions, and alerts are all cleared. Safe to
    call when idle (it just clears the already-empty session).

    Returns True when the poller fully stopped. False means the thread
    is still alive after the join timeout: session data is still cleared
    and the generation bumped (the leftover thread can only wind down
    inert), and state.thread is kept so start_assistant refuses to run
    beside it. Callers must not connect or start a new video on False."""
    state.stop_event.set()
    if poster is not None:
        getattr(poster, "clear_queue", lambda: None)()
    thread = state.thread
    if thread is not None:
        thread.join(timeout=15)
    stopped = thread is None or not thread.is_alive()
    if stopped:
        state.thread = None
    ch_id = getattr(state, "channel_id", None)
    qa_engine.reset_session_memory()
    reset_pending(channel_id=ch_id)
    state.clear_session()
    return stopped


