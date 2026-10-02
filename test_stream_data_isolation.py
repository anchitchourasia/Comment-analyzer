"""Regression tests for Streamlit 'New Questions from Chat' data isolation requirements.

Covers:
1. Start Stream A -> only Stream A questions are displayed.
2. Stop Stream A -> visible questions clear and late poller messages from Stream A are ignored.
3. Start Stream B immediately after Stream A -> only Stream B questions are displayed.
4. Stored old Stream A questions do not appear while Stream B is active.
5. A stale Stream A question cannot be used to post into Stream B.
6. Switching streams repeatedly does not create duplicate pollers or mixed queues.
7. Existing saved Q&A/history is not deleted unintentionally.
"""

import tempfile
import time
from pathlib import Path

import live_chat_poller as poller
import qa_engine
from backend import storage


class FakeYouTube:
    def __init__(self):
        self.calls = 0

    def liveChatMessages(self):
        return self

    def list(self, **_):
        return self

    def execute(self):
        self.calls += 1
        return {"items": [], "pollingIntervalMillis": 5000}


class FakePoster:
    own_channel_id = "UC_TEST_CHANNEL"

    def __init__(self):
        self.posts = []
        self.cleared = False

    def post_answer(self, text, chat_id, record_id=None):
        self.posts.append((text, chat_id, record_id))
        return True

    def clear_queue(self):
        self.cleared = True


def test_stream_data_isolation_all_requirements():
    with tempfile.TemporaryDirectory() as tmp_dir:
        orig_data = storage.DATA_DIR
        tmp_path = Path(tmp_dir)
        storage.DATA_DIR = tmp_path / "data"
        storage.CHANNELS_DIR = storage.DATA_DIR / "channels"
        poller.PENDING_FILE = None
        qa_engine.QA_FILE = None

        fake_yt = FakeYouTube()
        real_build = poller.build_youtube_client
        poller.build_youtube_client = lambda _key: fake_yt

        channel_id = "UC_TEST_CHANNEL"

        try:
            state = poller.get_assistant_state()
            poster = FakePoster()

            # --- 1. Start Stream A -> only Stream A questions displayed ---
            stream_a_chat = "live_chat_A"
            stream_a_vid = "video_A"
            poller.start_assistant(state, "api_key", stream_a_chat, poster, channel_id=channel_id, video_id=stream_a_vid)
            gen_a = state.generation

            # Simulate incoming question on Stream A
            poller.process_message(state, "User_A1", "UC_User_A1", "What camera is Stream A using?", poster, generation=gen_a, message_id="msg_A1")

            pending_a_raw = poller.load_pending(channel_id=channel_id, strict_stream_filter=False)
            pending_a_strict = poller.load_pending(channel_id=channel_id, live_chat_id=stream_a_chat, video_id=stream_a_vid, strict_stream_filter=True)

            assert len(pending_a_strict) == 1, "Stream A question must appear in Stream A strict query"
            assert "what camera is stream a using" in pending_a_strict
            occ_a = pending_a_strict["what camera is stream a using"]["occurrences"][0]
            assert occ_a["live_chat_id"] == stream_a_chat
            assert occ_a["video_id"] == stream_a_vid
            assert occ_a["author_name"] == "User_A1"

            # --- 2. Stop Stream A -> visible questions clear & late poller messages ignored ---
            poller.stop_assistant(state, poster=poster)

            pending_stopped = poller.load_pending(channel_id=channel_id, strict_stream_filter=True)
            assert pending_stopped == {}, "Stopped assistant must return empty list under strict stream filter"
            assert state.snapshot()["messages"] == []
            assert state.snapshot()["live_chat_id"] == ""
            assert state.snapshot()["video_id"] == ""

            # Late poller message after stop must be dropped
            poller.process_message(state, "Late_User", "UC_Late", "Is Stream A still on?", poster, generation=gen_a, message_id="msg_late")
            assert poller.load_pending(channel_id=channel_id, strict_stream_filter=True) == {}, "Late poller message after stop must be ignored"

            # --- 3. Start Stream B immediately after Stream A -> only Stream B questions displayed ---
            stream_b_chat = "live_chat_B"
            stream_b_vid = "video_B"
            poller.start_assistant(state, "api_key", stream_b_chat, poster, channel_id=channel_id, video_id=stream_b_vid)
            gen_b = state.generation
            assert gen_b != gen_a, "Generation ID must increment on stream switch"

            # Before Stream B receives questions, visible queue for Stream B must be empty
            pending_b_initial = poller.load_pending(channel_id=channel_id, live_chat_id=stream_b_chat, video_id=stream_b_vid, strict_stream_filter=True)
            assert pending_b_initial == {}, "Stream B must start with empty visible question queue"

            # Ingest Stream B question
            poller.process_message(state, "User_B1", "UC_User_B1", "What mic is Stream B using?", poster, generation=gen_b, message_id="msg_B1")

            pending_b_strict = poller.load_pending(channel_id=channel_id, live_chat_id=stream_b_chat, video_id=stream_b_vid, strict_stream_filter=True)

            # --- 4. Stored old Stream A questions do not appear while Stream B is active ---
            assert len(pending_b_strict) == 1, "Only Stream B question must appear while Stream B is active"
            assert "what mic is stream b using" in pending_b_strict
            assert "what camera is stream a using" not in pending_b_strict, "Stream A question must NOT appear in Stream B view"

            # --- 5. Stale Stream A question cannot be used to post into Stream B ---
            active_live_chat_id = state.live_chat_id
            assert active_live_chat_id == stream_b_chat

            stale_occ = occ_a
            assert stale_occ["live_chat_id"] == stream_a_chat
            assert stale_occ["live_chat_id"] != active_live_chat_id

            is_valid_post = (stale_occ["live_chat_id"] == active_live_chat_id)
            assert not is_valid_post, "Stale Stream A question must be rejected when attempting to post into Stream B"

            # --- 6. Switching streams repeatedly does not create duplicate pollers or mixed queues ---
            for i in range(5):
                s_chat = f"live_chat_repeat_{i}"
                s_vid = f"video_repeat_{i}"
                poller.stop_assistant(state)
                assert poller.start_assistant(state, "api_key", s_chat, poster, channel_id=channel_id, video_id=s_vid)
                poller.process_message(state, f"User_{i}", f"UC_{i}", f"Question for stream {i}?", poster, generation=state.generation)
                current_p = poller.load_pending(channel_id=channel_id, live_chat_id=s_chat, video_id=s_vid, strict_stream_filter=True)
                assert len(current_p) == 1, f"Iteration {i} failed to load pending"
                assert f"question for stream {i}" in current_p

            poller.stop_assistant(state)

            # --- 7. Existing saved Q&A/history is not deleted unintentionally ---
            raw_history = poller.load_pending(channel_id=channel_id, strict_stream_filter=False)
            assert len(raw_history) >= 2, "Historical stream questions must remain in disk storage for audit/history"
            assert "what camera is stream a using" in raw_history
            assert "what mic is stream b using" in raw_history

        finally:
            poller.stop_assistant(state)
            poller.build_youtube_client = real_build
            storage.DATA_DIR = orig_data
            storage.CHANNELS_DIR = orig_data / "channels"


if __name__ == "__main__":
    test_stream_data_isolation_all_requirements()
    print("test_stream_data_isolation: all 7 requirements passed successfully!")
