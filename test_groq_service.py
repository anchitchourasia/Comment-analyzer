"""Self-check for groq_service, fully mocked: `python test_groq_service.py`.

No network, no real Groq/YouTube calls, no real JSON files touched:
the HTTP layer is a stub passed in via `post=`, and Q&A storage is
redirected to a temp dir. Covers: missing key (no call attempted),
draft + verify happy paths, the NO_ANSWER contract, malformed
responses, timeouts, and the non-AI Jaccard fallback with AI down.
"""

import os
import tempfile
from pathlib import Path

import requests

import groq_service
import qa_engine


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _StubPost:
    """Records every call; returns a payload or raises `exc`."""

    def __init__(self, payload=None, exc=None):
        self.calls = []
        self.payload = payload
        self.exc = exc

    def __call__(self, url, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return _FakeResponse(self.payload)


def check():
    original_key = os.environ.get("GROQ_API_KEY")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            # storage redirect: the real qa_data.json is never touched
            qa_engine.QA_FILE = Path(tmp) / "qa_data.json"
            record = qa_engine.add_question_answer(
                "Which camera do you use?", "Sony ZV-E10"
            )

            # 1. missing key: graceful result, and NO request attempted
            os.environ.pop("GROQ_API_KEY", None)
            stub = _StubPost()
            result = groq_service.review_question("what camera?", post=stub)
            assert result["ok"] is False, result
            assert result["answer"] == ""
            assert not stub.calls, "API call attempted without a key"

            # 2. draft happy path: payload parsed, auth + model wired
            os.environ["GROQ_API_KEY"] = "test-key"
            stub = _StubPost(
                payload={"choices": [{"message": {"content": "Sony ZV-E10."}}]}
            )
            result = groq_service.review_question("what camera?", post=stub)
            assert result["ok"] and result["reliable"], result
            assert result["answer"] == "Sony ZV-E10."
            assert stub.calls[0]["headers"]["Authorization"] == "Bearer test-key"
            assert stub.calls[0]["timeout"] == groq_service.TIMEOUT_SECONDS
            body = stub.calls[0]["json"]
            assert body["model"] == groq_service.DEFAULT_MODEL
            # approved Q&A is the context; the key never leaks into it
            user_content = body["messages"][1]["content"]
            assert "which camera do you use" in user_content
            assert "test-key" not in user_content

            # 3. verify mode: proposed answer is passed through for checking
            stub = _StubPost(
                payload={"choices": [{"message": {"content": "Yes."}}]}
            )
            groq_service.review_question(
                "q?", suggested_answer="old answer", post=stub
            )
            assert "old answer" in stub.calls[0]["json"]["messages"][1]["content"]

            # 4. NO_ANSWER contract: model says so -> reliable=False, no answer
            stub = _StubPost(
                payload={"choices": [{"message": {"content": "NO_ANSWER"}}]}
            )
            result = groq_service.review_question("q?", post=stub)
            assert result["ok"] is True and result["reliable"] is False
            assert result["answer"] == ""

            # 5. malformed responses: shapes that aren't a chat completion
            for payload in (
                {"unexpected": "shape"},
                {"choices": []},
                {"choices": [{"message": {}}]},
                [],
            ):
                result = groq_service.review_question(
                    "q?", post=_StubPost(payload=payload)
                )
                assert result["ok"] is False, payload
                assert result["answer"] == ""

            # 6. timeout and network failure: surfaced, never raised
            stub = _StubPost(exc=requests.exceptions.Timeout("t"))
            result = groq_service.review_question("q?", post=stub)
            assert result["ok"] is False
            assert "timed out" in result["note"].lower()

            stub = _StubPost(exc=requests.exceptions.ConnectionError("x"))
            result = groq_service.review_question("q?", post=stub)
            assert result["ok"] is False

            # 7. non-AI fallback: with AI down and no key at all, the
            # Jaccard matcher still answers from approved memory
            os.environ.pop("GROQ_API_KEY", None)
            result = groq_service.review_question(
                "what camera do you use?", post=_StubPost(
                    exc=requests.exceptions.Timeout("t")
                )
            )
            assert result["ok"] is False
            match, score = qa_engine.find_best_answer("what camera do you use")
            assert match and score > 0.0
            assert match["answer_text"] == "Sony ZV-E10"
            assert match["id"] == record["id"]
    finally:
        if original_key is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = original_key

    print("test_groq_service: all checks passed")


if __name__ == "__main__":
    check()
