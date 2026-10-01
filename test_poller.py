"""Self-check for live_chat_poller logic: `python test_poller.py`.

No network, no nltk — is_question, IdRing, negative_share, AssistantState
suggestion bookkeeping, the pending queue, and the ignored-bots filter
(faked chat items, stub analyzer, temp-dir storage only). The video-switch
check runs the real poller thread against a fake YouTube client and stub
posters, with in-memory session storage.
"""

import tempfile
import time
from pathlib import Path

import live_chat_poller as poller
import qa_engine


def check():
    # is_question: positives
    for text in [
        "which camera do you use?",
        "how do you export?",
        "anyone know the song?",
        "where are you from",
        "can someone help",
        "what mic is that!!!",
    ]:
        assert poller.is_question(text), text

    # is_question: negatives
    for text in [
        "nice stream!",
        "lets gooo",
        "PogChamp",
        "",
        "   ",
    ]:
        assert not poller.is_question(text), text

    # IdRing: dedup + bounded eviction
    ring = poller.IdRing(maxlen=3)
    assert ring.add_if_new("a") and ring.add_if_new("b") and ring.add_if_new("c")
    assert not ring.add_if_new("a")
    assert ring.add_if_new("d"), "d should evict a from the ring"
    assert ring.add_if_new("a"), "a is new again after eviction"

    # negative_share
    messages = [{"sentiment": s} for s in (-0.5, -0.6, 0.8, 0.1)]
    assert abs(poller.negative_share(messages) - 0.5) < 1e-9
    assert poller.negative_share([]) == 0.0

    # AssistantState suggestions: no duplicates, removal by id
    state = poller.AssistantState()
    state.add_suggestion("q1?", "ans", 0.6, "viewer", record_id="q_x")
    state.add_suggestion("q1?", "ans", 0.6, "viewer", record_id="q_x")
    assert len(state.snapshot()["suggestions"]) == 1, "duplicate suggestion"

    sid = state.snapshot()["suggestions"][0]["id"]
    removed = state.remove_suggestion(sid)
    assert removed is not None and removed["record_id"] == "q_x"
    assert not state.snapshot()["suggestions"]

    # pending queue: aggregates by normalized text, newest example first
    with tempfile.TemporaryDirectory() as tmp:
        poller.PENDING_FILE = Path(tmp) / "pending_questions.json"

        poller.upsert_pending("What GPU for editing?")
        poller.upsert_pending("what gpu for editing??")
        pending = poller.load_pending()
        assert len(pending) == 1, "repeat ask did not aggregate"
        entry = pending["what gpu for editing"]
        assert entry["count"] == 2
        assert len(entry["examples"]) == 2

        poller.remove_pending("what gpu for editing")
        assert poller.load_pending() == {}


class _FakeAnalyzer:
    def polarity_scores(self, _text):
        return {"compound": 0.0}


def _chat_item(mid, name, channel_id, text):
    return {
        "id": mid,
        "snippet": {
            "type": "textMessageEvent",
            "textMessageDetails": {"messageText": text},
        },
        "authorDetails": {"displayName": name, "channelId": channel_id},
    }


def check_ignored_bots():
    with tempfile.TemporaryDirectory() as tmp:
        # redirect storage + matcher memory so no real JSON is touched
        qa_engine.QA_FILE = Path(tmp) / "qa_data.json"
        poller.PENDING_FILE = Path(tmp) / "pending_questions.json"
        qa_engine.add_question_answer(
            "Which camera do you use?", "Sony ZV-E10"
        )

        state = poller.AssistantState()
        state.set_ignored_bots("Streamlabs, UCchan123\n\n  nightbot  ")

        # is_ignored: complete name, case-insensitive; partial never matches
        assert state.is_ignored("streamLabs", "")
        assert state.is_ignored("Nightbot user", "other") is False
        assert state.is_ignored("anyone", "UCchan123")   # channel id match
        assert state.is_ignored("UCchan123", "") is False  # id isn't a name

        watch = [
            _chat_item("m1", "Streamlabs", "UCs1", "Which camera do you use?"),
            _chat_item("m2", "STREAMLABS", "UCs2", "Which camera do you use?"),
            _chat_item("m3", "Streamlabs fan", "UCs3", "Which camera do you use?"),
            _chat_item("m4", "UCchan123", "UCchan123", "How big is the room?"),
            _chat_item("m5", "me", "UCown", "How big is the room?"),  # echo guard
            _chat_item("m6", "viewer", "UCv", "Which camera do you use?"),
            _chat_item("m7", "viewer2", "UCw", "How big is the room?"),
        ]
        poller.ingest_items(
            state, watch, poller.IdRing(), _FakeAnalyzer(), "UCown", None
        )

        # feed: bots and echo invisible, partial name visible
        feed_authors = [m["author"] for m in state.snapshot()["messages"]]
        assert feed_authors == ["Streamlabs fan", "viewer", "viewer2"], feed_authors

        # suggestions: only the real viewer's camera question
        suggestions = state.snapshot()["suggestions"]
        assert len(suggestions) == 1, suggestions
        assert suggestions[0]["author"] == "Streamlabs fan"

        # pending: no bot/echo question ever enqueued
        pending = poller.load_pending()
        assert pending.keys() == {"how big is the room"}, pending
        assert pending["how big is the room"]["count"] == 1

        # updating the list takes effect immediately — no restart
        state.set_ignored_bots("streamlabs fan")
        assert not state.is_ignored("nightbot", "")
        assert state.is_ignored("StreamLabs Fan", "")


def check_video_switch():
    """Connect-time video switch: stopping A fully clears its session, a
    stale A can never poll/match/post again, B starts with empty memory,
    and a thread that won't stop blocks the switch. Real poller thread,
    fake YouTube client, stub posters — no network."""
    qa_engine.QA_FILE = None       # production storage: in-memory session
    poller.PENDING_FILE = None

    class FakeYouTube:
        def __init__(self, items):
            self.items = items
            self.calls = 0

        def liveChatMessages(self):
            return self

        def list(self, **_):
            return self

        def execute(self):
            self.calls += 1
            return {"items": self.items, "pollingIntervalMillis": 5000}

    class FakePoster:
        own_channel_id = "UCown"

        def __init__(self):
            self.posts = []

        def post_answer(self, text, chat_id, record_id=None):
            self.posts.append((text, chat_id, record_id))
            return True

    class _Zombie:
        def is_alive(self):
            return True

        def join(self, timeout=None):
            pass

    fake = FakeYouTube([])
    real_build = poller.build_youtube_client
    real_analyzer = poller._get_analyzer
    poller.build_youtube_client = lambda _key: fake
    poller._get_analyzer = lambda: _FakeAnalyzer()
    try:
        # --- session A: every stream starts empty (start_assistant wipes
        # memory on purpose), so wait for the first poll, then approve the
        # record and let the next poll ingest the question
        poster_a = FakePoster()
        state = poller.AssistantState()
        state.auto_reply = True
        assert poller.start_assistant(state, "key", "chatA", poster_a)
        gen_a = state.generation

        deadline = time.time() + 10
        while fake.calls < 1 and time.time() < deadline:
            time.sleep(0.05)
        qa_engine.add_question_answer(
            "Which camera do you use?", "Sony ZV-E10", auto_reply=True
        )
        fake.items = [
            _chat_item("a1", "viewer", "UCv", "Which camera do you use?")
        ]

        deadline = time.time() + 15
        while not poster_a.posts and time.time() < deadline:
            time.sleep(0.05)
        assert poster_a.posts, "A never matched/posted its question"
        assert poster_a.posts[0][1] == "chatA"

        # --- the switch: stopping A fully clears its session
        assert poller.stop_assistant(state) is True
        assert state.thread is None
        assert qa_engine.load_qa_data() == [], "A's Q&A memory survived"
        assert poller.load_pending() == {}, "A's pending queue survived"
        snap = state.snapshot()
        assert snap["messages"] == [] and snap["suggestions"] == []
        assert snap["live_chat_id"] == ""

        # A cannot keep polling: thread dead, no further list() calls
        calls_at_stop = fake.calls
        time.sleep(0.3)
        assert fake.calls == calls_at_stop, "dead poller kept polling"

        # --- session B starts empty
        fake.items = []
        poster_b = FakePoster()
        assert poller.start_assistant(state, "key", "chatB", poster_b)
        gen_b = state.generation
        assert gen_b != gen_a
        assert qa_engine.load_qa_data() == [], "B inherited A's memory"
        assert poller.load_pending() == {}
        snap = state.snapshot()
        assert snap["messages"] == [] and snap["suggestions"] == []

        # --- stale A can never match or post in B's session
        qa_engine.add_question_answer(
            "Which camera do you use?", "Sony ZV-E10", auto_reply=True
        )
        poller.process_message(
            state, "viewer", "UCv", "Which camera do you use?",
            poster_b, generation=gen_a,
        )
        assert poster_b.posts == [], "stale A posted into B's session"
        assert poller.load_pending() == {}, "stale A enqueued into B"
        assert state.snapshot()["suggestions"] == []

        # control: the CURRENT generation still posts — the guard blocks A
        poller.process_message(
            state, "viewer", "UCv", "Which camera do you use?",
            poster_b, generation=gen_b,
        )
        assert poster_b.posts, "current generation failed to post"

        assert poller.stop_assistant(state) is True
    finally:
        poller.build_youtube_client = real_build
        poller._get_analyzer = real_analyzer

    # --- failed stop blocks the switch: thread kept alive -> no B
    state = poller.AssistantState()
    state.thread = _Zombie()
    assert poller.stop_assistant(state) is False
    assert state.thread.is_alive(), "failed stop must keep the thread ref"
    assert poller.start_assistant(state, "key", "chatB", None) is False, (
        "start must refuse while A's thread is still alive"
    )


def check_channel_poller_persistence():
    from backend import storage
    with tempfile.TemporaryDirectory() as tmp:
        orig_data = storage.DATA_DIR
        storage.DATA_DIR = Path(tmp) / "data"
        storage.CHANNELS_DIR = storage.DATA_DIR / "channels"
        poller.PENDING_FILE = None
        qa_engine.QA_FILE = None
        try:
            state = poller.AssistantState()
            poller.start_assistant(state, "key", "chat_test", None, channel_id="UC_TEST_PERSIST")
            assert state.channel_id == "UC_TEST_PERSIST"

            # Ingest an unknown question
            poller.process_message(state, "viewer1", "UCv1", "What software is this?", None)

            # Check that pending was saved into channel storage file
            pending_chan = poller.load_pending(channel_id="UC_TEST_PERSIST")
            assert len(pending_chan) == 1
            assert "what software is this" in pending_chan

            # Stop assistant
            poller.stop_assistant(state)

            # Verify persistent data on disk survived assistant stop
            reloaded_pending = poller.load_pending(channel_id="UC_TEST_PERSIST")
            assert len(reloaded_pending) == 1
            assert "what software is this" in reloaded_pending
        finally:
            storage.DATA_DIR = orig_data
            storage.CHANNELS_DIR = orig_data / "channels"


if __name__ == "__main__":
    check()
    check_ignored_bots()
    check_video_switch()
    check_channel_poller_persistence()
    print("test_poller: all checks passed")
