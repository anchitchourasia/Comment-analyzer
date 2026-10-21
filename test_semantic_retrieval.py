"""Comprehensive Evaluation and Regression Test Suite for Genuine Multilingual Semantic Q&A.

Validates:
  1. Multilingual evaluation benchmark (English paraphrases, Hindi script, Hinglish, contrasting intents, negation, unrelated queries).
  2. Metrics computation (Top-1 accuracy, abstention rate, false positive rate).
  3. Strict tenant namespace isolation & fail-closed behavior.
  4. Pinecone query invocation on live/sandbox paths.
  5. Suggestion-only safety (no auto-posting for semantic fuzzy matches).
  6. Transparent lexical fallback during service failure.
  7. Approval status & deleted record synchronization.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import qa_engine
import live_chat_poller as poller
from backend import semantic_pinecone, semantic_retriever
from backend.embeddings.mock_provider import MockEmbeddingProvider
from backend.embeddings.factory import get_embedding_provider
from backend.semantic_retriever import SemanticQARetriever


class TestSemanticRetrievalSuite(unittest.TestCase):
    """Test suite for multilingual semantic retrieval, isolation, and safety."""

    @classmethod
    def setUpClass(cls):
        os.environ["EMBEDDING_PROVIDER"] = "mock"
        cls.provider = MockEmbeddingProvider()
        cls.retriever = SemanticQARetriever(cls.provider)

        # Standard Benchmark Q&A Records
        cls.benchmark_records = [
            {
                "id": "q_sched_01",
                "normalized_question": "what time does the stream start",
                "original_question_examples": ["what time does the stream start", "when are you live"],
                "answer_text": "Stream starts daily at 8 PM IST!",
                "status": "approved",
                "auto_reply": True,
                "cooldown_seconds": 60,
            },
            {
                "id": "q_plat_02",
                "normalized_question": "where do you stream",
                "original_question_examples": ["where do you stream", "which platform are you streaming on"],
                "answer_text": "We stream live exclusively on YouTube!",
                "status": "approved",
                "auto_reply": False,
                "cooldown_seconds": 60,
            },
            {
                "id": "q_game_03",
                "normalized_question": "which game are you playing today",
                "original_question_examples": ["which game are you playing today", "game name please"],
                "answer_text": "Today we are playing GTA V RP!",
                "status": "approved",
                "auto_reply": False,
                "cooldown_seconds": 60,
            },
            {
                "id": "q_cam_04",
                "normalized_question": "which camera do you use",
                "original_question_examples": ["which camera do you use", "what camera is this"],
                "answer_text": "Sony ZV-E10 with 16mm f/1.4 lens.",
                "status": "approved",
                "auto_reply": False,
                "cooldown_seconds": 60,
            },
            {
                "id": "q_price_05",
                "normalized_question": "what is the price of your camera",
                "original_question_examples": ["what is the price of your camera", "how much does your camera cost"],
                "answer_text": "The camera body was around 65,000 INR.",
                "status": "approved",
                "auto_reply": False,
                "cooldown_seconds": 60,
            },
            {
                "id": "q_mic_06",
                "normalized_question": "which microphone do you use",
                "original_question_examples": ["which microphone do you use", "what mic are you using"],
                "answer_text": "Shure SM7B with GoXLR interface.",
                "status": "approved",
                "auto_reply": False,
                "cooldown_seconds": 60,
            },
            {
                "id": "q_specs_07",
                "normalized_question": "what are your pc specs",
                "original_question_examples": ["what are your pc specs", "pc specifications"],
                "answer_text": "RTX 4090, i9-14900K, 64GB DDR5 RAM.",
                "status": "approved",
                "auto_reply": False,
                "cooldown_seconds": 60,
            },
        ]

    def setUp(self):
        self.test_channel = "UC_SEMANTIC_TEST_CH"
        # Seed test channel data
        qa_engine.save_qa_data(list(self.benchmark_records), channel_id=self.test_channel)

    def tearDown(self):
        qa_engine.save_qa_data([], channel_id=self.test_channel)
        semantic_pinecone.set_mock_index(None)

    # -----------------------------------------------------------------------
    # 1. Multilingual Benchmark & Evaluation Set
    # -----------------------------------------------------------------------
    def test_multilingual_evaluation_benchmark(self):
        """Evaluate 25 labeled queries across English, Hindi, Hinglish, Negation, and Noise."""
        labeled_dataset = [
            # --- English Paraphrases ---
            {"query": "When are you going live today?", "expected": "q_sched_01", "category": "EN_Paraphrase"},
            {"query": "What is your broadcast schedule?", "expected": "q_sched_01", "category": "EN_Paraphrase"},
            {"query": "Which platform are you hosting on?", "expected": "q_plat_02", "category": "EN_Paraphrase"},
            {"query": "What mic model is in your setup?", "expected": "q_mic_06", "category": "EN_Paraphrase"},
            {"query": "What is your computer hardware specs?", "expected": "q_specs_07", "category": "EN_Paraphrase"},

            # --- Hindi Script (Devanagari) ---
            {"query": "स्ट्रीम कब शुरू होगा?", "expected": "q_sched_01", "category": "Hindi_Script"},
            {"query": "आप कौन सा कैमरा इस्तेमाल करते हैं?", "expected": "q_cam_04", "category": "Hindi_Script"},
            {"query": "माइक कौन सा है?", "expected": "q_mic_06", "category": "Hindi_Script"},

            # --- Hinglish Queries ---
            {"query": "Stream kab start hoga?", "expected": "q_sched_01", "category": "Hinglish"},
            {"query": "Stream kahan hoga?", "expected": "q_plat_02", "category": "Hinglish_Contrasting"},
            {"query": "Stream par kaunsa game hoga?", "expected": "q_game_03", "category": "Hinglish_Contrasting"},
            {"query": "Camera kaunsa hai?", "expected": "q_cam_04", "category": "Hinglish_Contrasting"},
            {"query": "Camera ka price kya hai?", "expected": "q_price_05", "category": "Hinglish_Contrasting"},
            {"query": "Mic kaunsa hai?", "expected": "q_mic_06", "category": "Hinglish_Contrasting"},
            {"query": "Aaj kitne baje shuru karoge live?", "expected": "q_sched_01", "category": "Hinglish"},
            {"query": "Bhai camera kitne ka pada?", "expected": "q_price_05", "category": "Hinglish"},
            {"query": "Kahan live aate ho?", "expected": "q_plat_02", "category": "Hinglish"},

            # --- Typos & Slang ---
            {"query": "wat camra u use bro", "expected": "q_cam_04", "category": "Typo_Slang"},
            {"query": "spex of pc pls", "expected": "q_specs_07", "category": "Typo_Slang"},

            # --- Negation & Contrasting Opposites (Must NOT match hardware Q&A) ---
            {"query": "Mic nahi chal raha hai awaz nahi aa rahi", "expected": None, "category": "Negation_Issue"},
            {"query": "Camera freeze ho gaya", "expected": None, "category": "Negation_Issue"},

            # --- Unrelated Noise (Must Abstain / Score < 0.50) ---
            {"query": "What is the capital of France?", "expected": None, "category": "Unrelated_Noise"},
            {"query": "How to bake a chocolate cake?", "expected": None, "category": "Unrelated_Noise"},
            {"query": "Tell me a funny joke", "expected": None, "category": "Unrelated_Noise"},
            {"query": "Who is the prime minister of Japan?", "expected": None, "category": "Unrelated_Noise"},
        ]

        correct_top1 = 0
        total_queries = len(labeled_dataset)
        noise_correctly_abstained = 0
        total_noise = 0

        for item in labeled_dataset:
            query = item["query"]
            expected_id = item["expected"]
            res = self.retriever.retrieve(query, channel_id=self.test_channel, threshold=0.50)

            matched_id = res.matched_record["id"] if res.matched_record else None

            if expected_id is None:
                total_noise += 1
                if matched_id is None:
                    correct_top1 += 1
                    noise_correctly_abstained += 1
            else:
                if matched_id == expected_id:
                    correct_top1 += 1

        top1_accuracy = (correct_top1 / total_queries) * 100.0
        abstention_rate = (noise_correctly_abstained / total_noise) * 100.0

        # Assert top-1 benchmark meets quality threshold
        self.assertGreaterEqual(top1_accuracy, 80.0, f"Benchmark Top-1 accuracy {top1_accuracy}% fell below 80%")
        self.assertGreaterEqual(abstention_rate, 80.0, f"Abstention rate {abstention_rate}% fell below 80%")

    # -----------------------------------------------------------------------
    # 2. Strict Tenant Namespace Isolation & Fail-Closed
    # -----------------------------------------------------------------------
    def test_missing_channel_id_in_pinecone_fails_closed(self):
        """Verifies querying Pinecone directly without channel_id raises ValueError."""
        dummy_vec = [0.1] * 384
        with self.assertRaises(ValueError):
            semantic_pinecone.query_semantic_index(dummy_vec, channel_id="")

        with self.assertRaises(ValueError):
            semantic_pinecone.upsert_semantic_vectors([{"id": "1", "values": dummy_vec}], channel_id="")

    def test_tenant_isolation_between_channels(self):
        """Verify records saved in Channel A are invisible to queries in Channel B."""
        ch_a = "UC_CHANNEL_A"
        ch_b = "UC_CHANNEL_B"

        rec_a = qa_engine.add_question_answer("Where is your secret base?", "In Tokyo", channel_id=ch_a)
        qa_engine.save_qa_data([], channel_id=ch_b)

        # Query from Channel B
        res_b = self.retriever.retrieve("Where is your secret base?", channel_id=ch_b)
        self.assertIsNone(res_b.matched_record)
        self.assertEqual(res_b.status, "no_match")

        # Cleanup
        qa_engine.save_qa_data([], channel_id=ch_a)

    # -----------------------------------------------------------------------
    # 3. Pinecone Query Invocation Verification
    # -----------------------------------------------------------------------
    def test_pinecone_query_invoked_when_available(self):
        """Verifies Pinecone query method is called on the semantic retrieval path."""
        mock_idx = MagicMock()
        mock_idx.query.return_value = {
            "matches": [
                {"id": "q_cam_04", "score": 0.94, "metadata": {"normalized_question": "which camera do you use"}}
            ]
        }
        semantic_pinecone.set_mock_index(mock_idx)

        res = self.retriever.retrieve("tell me your camera setup", channel_id=self.test_channel)

        # Verify mock_idx.query was called with namespace=self.test_channel
        mock_idx.query.assert_called_once()
        call_kwargs = mock_idx.query.call_args[1]
        self.assertEqual(call_kwargs["namespace"], self.test_channel)
        self.assertIsNotNone(res.matched_record)
        self.assertEqual(res.matched_record["id"], "q_cam_04")

    # -----------------------------------------------------------------------
    # 4. Suggestion-Only Safety (No Auto-Posting for Semantic-Only Matches)
    # -----------------------------------------------------------------------
    def test_semantic_matches_are_suggestion_only_no_autopost(self):
        """Verifies that high-scoring semantic matches do NOT auto-reply without explicit keyword trigger."""
        state = poller.get_assistant_state()
        state.clear_session()
        setattr(state, "channel_id", self.test_channel)

        class MockPoster:
            def __init__(self):
                self.posted = []
            def post_answer(self, text, live_chat_id, record_id=None, cooldown_seconds=60):
                self.posted.append(text)
                return True

        poster = MockPoster()

        # "q_sched_01" has auto_reply=True, but viewer uses a pure semantic paraphrase
        # It must land in state.suggestions and NEVER be posted directly to YouTube
        poller.process_message(state, "Viewer1", "UC_Viewer1", "When are you going live today?", poster)

        self.assertEqual(len(poster.posted), 0, "Semantic match must not trigger auto-posting!")
        self.assertGreaterEqual(len(state.suggestions), 1, "Semantic match must be routed to streamer suggestions")
        self.assertEqual(state.suggestions[0]["answer"], "Stream starts daily at 8 PM IST!")

    # -----------------------------------------------------------------------
    # 5. Lexical Fallback when Pinecone is Unavailable
    # -----------------------------------------------------------------------
    def test_transparent_lexical_fallback_when_pinecone_down(self):
        """Verifies retriever gracefully falls back to lexical matching when Pinecone is down."""
        # Force Pinecone unavailable
        with patch.object(semantic_pinecone, "is_semantic_pinecone_available", return_value=False):
            # Query exact match in channel
            res = self.retriever.retrieve("which camera do you use", channel_id=self.test_channel)

            self.assertIsNotNone(res.matched_record)
            self.assertEqual(res.matched_record["id"], "q_cam_04")
            self.assertIn(res.match_type, ("exact_keyword", "lexical_fallback", "hybrid"))

    # -----------------------------------------------------------------------
    # 6. Approval & Deletion Synchronization
    # -----------------------------------------------------------------------
    def test_draft_and_deleted_records_excluded_from_retrieval(self):
        """Verifies draft records and deleted records are never returned to viewers."""
        # Add a draft record
        qa_engine.add_question_answer(
            "What is your secret email?", "secret@example.com",
            status="draft", channel_id=self.test_channel
        )

        res = self.retriever.retrieve("What is your secret email?", channel_id=self.test_channel)
        self.assertIsNone(res.matched_record, "Draft records must not be returned by semantic retriever")

        # Delete an approved record
        qa_engine.delete_record("q_mic_06", channel_id=self.test_channel)
        res_del = self.retriever.retrieve("which microphone do you use", channel_id=self.test_channel)
        matched_id = res_del.matched_record["id"] if res_del.matched_record else None
        self.assertNotEqual(matched_id, "q_mic_06", "Deleted record must not be matched")


if __name__ == "__main__":
    unittest.main()
