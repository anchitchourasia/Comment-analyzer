import time
import tempfile
import json
import shutil
from pathlib import Path


from backend import storage
import qa_engine
import live_chat_poller
from answer_poster import AnswerPoster
from scripts.migrate_m1 import migrate_m1

class MockInsert:
    def __init__(self, mock_client, body):
        self.mock_client = mock_client
        self.body = body

    def execute(self):
        self.mock_client.posted_messages.append({
            "timestamp": time.time(),
            "body": self.body
        })
        return {"id": "mock_msg_id"}

class MockLiveChatMessages:
    def __init__(self, mock_client):
        self.mock_client = mock_client

    def insert(self, part, body):
        return MockInsert(self.mock_client, body)

class MockYouTubeClient:
    def __init__(self):
        self.posted_messages = []

    def liveChatMessages(self):
        return MockLiveChatMessages(self)

def run_tests():
    # Save original DATA_DIR
    orig_data_dir = storage.DATA_DIR
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        test_data_dir = temp_dir / "data"
        storage.DATA_DIR = test_data_dir
        storage.CHANNELS_DIR = test_data_dir / "channels"

        # --- Test 1: Storage Path Validation ---
        assert storage.validate_channel_id("UC123456789") == "UC123456789"
        try:
            storage.validate_channel_id("../evil_path")
            assert False, "Should have raised ValueError for path traversal"
        except ValueError:
            pass

        # --- Test 2: A/B Channel Data Isolation (Q&A and Pending) ---
        qa_engine.add_question_answer("Question for A", "Answer A", channel_id="UC_CHANNEL_A")
        qa_engine.add_question_answer("Question for B", "Answer B", channel_id="UC_CHANNEL_B")

        data_a = qa_engine.load_qa_data(channel_id="UC_CHANNEL_A")
        data_b = qa_engine.load_qa_data(channel_id="UC_CHANNEL_B")

        assert len(data_a) == 1
        assert len(data_b) == 1
        assert data_a[0]["answer_text"] == "Answer A"
        assert data_b[0]["answer_text"] == "Answer B"
        assert (test_data_dir / "channels" / "UC_CHANNEL_A" / "qa_data.json").exists()
        assert (test_data_dir / "channels" / "UC_CHANNEL_B" / "qa_data.json").exists()

        # Pending questions isolation
        live_chat_poller.upsert_pending("Pending q for A", channel_id="UC_CHANNEL_A")
        live_chat_poller.upsert_pending("Pending q for B", channel_id="UC_CHANNEL_B")

        pending_a = live_chat_poller.load_pending(channel_id="UC_CHANNEL_A")
        pending_b = live_chat_poller.load_pending(channel_id="UC_CHANNEL_B")

        assert len(pending_a) == 1
        assert len(pending_b) == 1
        assert "pending q for a" in pending_a
        assert "pending q for b" in pending_b

        # --- Test 3: Restart Persistence ---
        # Reloading QA and Pending from disk for UC_CHANNEL_A
        qa_reloaded = qa_engine.load_qa_data(channel_id="UC_CHANNEL_A")
        assert len(qa_reloaded) == 1
        assert qa_reloaded[0]["answer_text"] == "Answer A"

        # --- Test 4: Migration Idempotency ---
        # Create dummy root qa_data.json
        src_qa = temp_dir / "qa_data.json"
        src_qa.write_text(json.dumps([{"question": "Root Q", "answer": "Root A"}]), encoding="utf-8")
        
        # Override migrate_m1 BASE_DIR
        import scripts.migrate_m1 as migrate_mod
        orig_base = migrate_mod.BASE_DIR
        migrate_mod.BASE_DIR = temp_dir

        res1 = migrate_m1("UC_MIGRATED")
        assert res1 is True
        migrated_qa = json.loads((test_data_dir / "channels" / "UC_MIGRATED" / "qa_data.json").read_text(encoding="utf-8"))
        assert len(migrated_qa) == 1

        # Second migration call (idempotent)
        res2 = migrate_m1("UC_MIGRATED")
        assert res2 is True
        migrated_qa_2 = json.loads((test_data_dir / "channels" / "UC_MIGRATED" / "qa_data.json").read_text(encoding="utf-8"))
        assert len(migrated_qa_2) == 1  # Not duplicated

        migrate_mod.BASE_DIR = orig_base

        # --- Test 5: Distinct Channels Cooldown & Poster Isolation ---
        mock_yt = MockYouTubeClient()
        poster_a = AnswerPoster(session_token="test", channel_id="UC_A")
        poster_a.youtube = mock_yt

        poster_b = AnswerPoster(session_token="test", channel_id="UC_B")
        poster_b.youtube = mock_yt

        # Verify posters write to distinct cooldown and log files
        assert poster_a.cooldown_path != poster_b.cooldown_path
        assert "UC_A" in str(poster_a.cooldown_path)
        assert "UC_B" in str(poster_b.cooldown_path)

        poster_a.post_answer("Answer on A", "chat_A", record_id="rec_1")
        poster_a.wait_for_queue()

        # Channel B should NOT be in cooldown for rec_1 because rec_1 was posted on Channel A
        assert poster_a.cooldown_active("rec_1") is True
        assert poster_b.cooldown_active("rec_1") is False

        # --- Test 6: Single-Writer Rule per Channel ---
        try:
            poster_a_duplicate = AnswerPoster(session_token="test", channel_id="UC_A")
            assert False, "Should have raised RuntimeError for duplicate active poster on same channel"
        except RuntimeError as e:
            assert "Single-writer rule enforced" in str(e)

        poster_a.stop()
        poster_b.stop()

        # After stop, a new poster for UC_A is allowed
        poster_a_new = AnswerPoster(session_token="test", channel_id="UC_A")
        poster_a_new.stop()

    # Restore original storage paths
    storage.DATA_DIR = orig_data_dir
    storage.CHANNELS_DIR = orig_data_dir / "channels"
    print("test_m1_channel: all checks passed")

if __name__ == "__main__":
    run_tests()
