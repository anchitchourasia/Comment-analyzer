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
            def post_answer(self, text, live_chat_id, record_id=None):
                self.posted.append(text)
                return True

        poster = DummyPoster()
        # Viewer types "pc specs" in live chat without question mark
        poller.process_message(state, "Viewer1", "UC_Viewer1", "pc specs", poster)

        # Must auto-post directly and not land in suggestions or pending
        self.assertEqual(poster.posted, ["PC HP PAVILLION 3050 RTX graphics"])
        self.assertEqual(len(state.suggestions), 0)

if __name__ == "__main__":
    unittest.main()
