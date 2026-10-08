import unittest
import qa_engine
import live_chat_poller as poller
from backend.models import QaMemoryCreateRequest

class TestKeywordTriggers(unittest.TestCase):
    def setUp(self):
        qa_engine.reset_session_memory()
        poller.reset_pending()

    def test_save_and_retrieve_keyword_triggers(self):
        record = qa_engine.add_question_answer(
            question="pc specs",
            answer="PC HP PAVILLION 3050 RTX graphics",
            auto_reply=True,
            keywords=["pc specs", "PC Specs", "hardware", "specs"]
        )
        self.assertIn("pc specs", record["original_question_examples"])
        self.assertIn("hardware", record["original_question_examples"])
        self.assertEqual(record["answer_text"], "PC HP PAVILLION 3050 RTX graphics")

    def test_find_best_answer_keyword_substring(self):
        qa_engine.add_question_answer(
            question="pc specs",
            answer="PC HP PAVILLION 3050 RTX graphics",
            auto_reply=True,
            keywords=["pc specs", "PC Specs"]
        )
        # Viewer asks "hey streamer what is your pc specs?"
        match, score = qa_engine.find_best_answer("hey streamer what is your pc specs?")
        self.assertIsNotNone(match)
        self.assertGreaterEqual(score, 0.8)
        self.assertEqual(match["answer_text"], "PC HP PAVILLION 3050 RTX graphics")

    def test_live_chat_non_question_keyword_auto_posting(self):
        qa_engine.add_question_answer(
            question="pc specs",
            answer="PC HP PAVILLION 3050 RTX graphics",
            auto_reply=True,
            keywords=["pc specs", "PC Specs"]
        )
        state = poller.get_assistant_state()
        state.clear_session()

        class DummyPoster:
            def __init__(self):
                self.posted = []
                self.last_posted = {}
            def post_answer(self, text, live_chat_id, record_id=None, cooldown_seconds=60):
                import time
                now = time.time()
                if record_id in self.last_posted:
                    if (now - self.last_posted[record_id]) < cooldown_seconds:
                        return False
                self.last_posted[record_id] = now
                self.posted.append(text)
                return True

        poster = DummyPoster()
        # Viewer types "pc specs" in live chat without question mark
        poller.process_message(state, "Viewer1", "UC_Viewer1", "pc specs", poster)

        # Must auto-post directly and not land in suggestions or pending
        self.assertEqual(poster.posted, ["PC HP PAVILLION 3050 RTX graphics"])
        self.assertEqual(len(state.suggestions), 0)

    def test_keyword_trigger_cooldown_prevents_spam(self):
        import time
        rec = qa_engine.add_question_answer(
            question="pc specs",
            answer="PC Specs: RTX 4090",
            auto_reply=True,
            keywords=["pc specs", "hardware"],
            cooldown_seconds=10
        )
        self.assertEqual(rec["cooldown_seconds"], 10)

        state = poller.get_assistant_state()
        state.clear_session()

        class CooldownAwarePoster:
            def __init__(self):
                self.posted = []
                self.last_posted = {}
            def post_answer(self, text, live_chat_id, record_id=None, cooldown_seconds=60):
                now = time.time()
                if record_id in self.last_posted:
                    if (now - self.last_posted[record_id]) < cooldown_seconds:
                        return False
                self.last_posted[record_id] = now
                self.posted.append(text)
                return True

        poster = CooldownAwarePoster()

        # First message triggers auto-posting
        poller.process_message(state, "Viewer1", "UC_1", "what is your pc specs?", poster)
        self.assertEqual(len(poster.posted), 1)

        # Immediate repeat message from another viewer during 10s cooldown must NOT post again
        poller.process_message(state, "Viewer2", "UC_2", "tell me pc specs please", poster)
        self.assertEqual(len(poster.posted), 1)
        self.assertEqual(len(state.suggestions), 0)

if __name__ == "__main__":
    unittest.main()
