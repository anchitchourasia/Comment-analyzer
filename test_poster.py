import time
import tempfile
import json
import threading
from pathlib import Path
from answer_poster import AnswerPoster, POST_COOLDOWN_SECONDS, GLOBAL_POST_GAP_SECONDS
import qa_engine
import answer_poster

class MockResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

class MockRequests:
    def __init__(self):
        self.posted_messages = []
        self.should_fail = False

    def post(self, url, headers=None, json=None):
        if self.should_fail:
            return MockResponse(500, "Backend API error: Quota Exceeded")
        
        self.posted_messages.append({
            "url": url,
            "headers": headers,
            "body": json
        })
        return MockResponse(200, "ok")

def run_tests():
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        cooldown_file = temp_dir / "cooldown.json"
        log_file = temp_dir / "posted_log.jsonl"
        qa_file = temp_dir / "qa_data.json"

        qa_engine.QA_FILE = qa_file
        qa_engine.reset_session_memory()

        mock_req = MockRequests()
        # Mock requests in answer_poster
        original_requests = answer_poster.requests
        answer_poster.requests = mock_req

        poster = AnswerPoster(session_token="test_token", channel_id="UC_TEST", cooldown_path=cooldown_file, log_path=log_file)

        # --- Test 1: Queue accepted ---
        start_t = time.time()
        res1 = poster.post_answer("Answer 1", "chat_1", record_id="rec_1")
        elapsed = time.time() - start_t
        assert res1 is True, "Test 1 failed"
        assert elapsed < 0.5, "Test 1 failed"

        poster.wait_for_queue()
        assert len(mock_req.posted_messages) == 1
        assert mock_req.posted_messages[0]["body"]["answer_text"] == "Answer 1"

        # --- Test 2: Cooldown rejected ---
        res_repeat = poster.post_answer("Answer 1 repeat", "chat_1", record_id="rec_1")
        assert res_repeat is False

        # --- Test 3: Save succeeds / post rejected ---
        record = qa_engine.add_question_answer("How to jump?", "Press spacebar", channel_id="UC_TEST")
        assert record["id"] is not None
        assert poster.post_answer("Press spacebar", "chat_1", record_id=record["id"]) is True
        poster.wait_for_queue()

        res_dup = poster.post_answer("Press spacebar again", "chat_1", record_id=record["id"])
        assert res_dup is False
        qa_records = qa_engine.load_qa_data(channel_id="UC_TEST")
        assert len(qa_records) == 1

        # --- Test 4: Worker API failure ---
        mock_req.should_fail = True
        poster.post_answer("Answer failure test", "chat_1", record_id="rec_fail")
        poster.wait_for_queue()
        assert poster.last_status == "error"
        assert "Quota Exceeded" in str(poster.last_error)
        mock_req.should_fail = False

        # --- Test 5: Stop with pending messages ---
        poster.post_answer("Answer stream A msg 1", "chat_A", record_id="rec_A1")
        poster.post_answer("Answer stream A msg 2", "chat_A", record_id="rec_A2")
        poster.clear_queue()
        poster.wait_for_queue()
        assert poster._queue.empty()

        # --- Test 6: Switch stream ---
        poster.post_answer("Stale message for chat A", "chat_A", record_id="rec_stale_A")
        poster.clear_queue()
        poster.post_answer("Fresh message for chat B", "chat_B", record_id="rec_fresh_B")
        poster.wait_for_queue()
        
        chat_b_messages = [m for m in mock_req.posted_messages if m["body"]["live_chat_id"] == "chat_B"]
        assert len(chat_b_messages) >= 1

        # --- Test 7: Two AnswerPoster instances ---
        poster2 = AnswerPoster(session_token="test_token", channel_id=None, cooldown_path=cooldown_file, log_path=log_file)
        
        assert poster2.cooldown_active("rec_1") is True
        assert poster2.post_answer("Duplicate via poster2", "chat_1", record_id="rec_1") is False

        assert poster2.post_answer("New via poster2", "chat_1", record_id="rec_p2_new") is True
        poster2.wait_for_queue()
        assert poster.cooldown_active("rec_p2_new") is True

        poster.stop()
        poster2.stop()

        answer_poster.requests = original_requests

    print("test_poster: all checks passed")

if __name__ == "__main__":
    run_tests()
