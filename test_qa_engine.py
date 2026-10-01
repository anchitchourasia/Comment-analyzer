"""Self-check for qa_engine v2: run with `python test_qa_engine.py`."""

import json
import tempfile
from pathlib import Path

import qa_engine


def check():
    with tempfile.TemporaryDirectory() as tmp:
        # Redirect storage so the test never touches the real qa_data.json
        qa_engine.QA_FILE = Path(tmp) / "qa_data.json"

        # v2 add: full record shape with defaults
        record = qa_engine.add_question_answer(
            "Which camera do you use?", "Sony ZV-E10"
        )
        assert record["id"].startswith("q_")
        assert record["normalized_question"] == "which camera do you use"
        assert record["answer_text"] == "Sony ZV-E10"
        assert record["status"] == "approved"
        assert record["auto_reply"] is False
        assert record["usage_count"] == 0
        assert record["created_at"] and record["updated_at"]
        assert record["last_used_at"] is None

        # dedup: same normalized question overwrites, keeps both raw examples
        qa_engine.add_question_answer(
            "WHICH CAMERA DO YOU USE?!", "Canon R50", auto_reply=True
        )
        data = qa_engine.load_qa_data()
        assert len(data) == 1, data
        assert data[0]["answer_text"] == "Canon R50"
        assert data[0]["auto_reply"] is True
        assert len(data[0]["original_question_examples"]) == 2

        # atomic save: no .tmp file left behind
        assert not list(Path(tmp).glob("*.tmp")), "stray .tmp after atomic save"

        # scoring (Phase 1 logic, unchanged)
        assert qa_engine.calculate_score(
            "which camera do you use", "which camera do you use"
        ) == 1.0
        assert qa_engine.calculate_score("camera lens", "lighting setup") == 0.0

        # matching: exact, partial, none
        match, score = qa_engine.find_best_answer(
            "Which camera do you use?", data
        )
        assert match and score == 1.0

        match, score = qa_engine.find_best_answer("what camera lens is that", data)
        assert match and 0 < score < 1.0

        match, score = qa_engine.find_best_answer("hello", data)
        assert match is None or score == 0.0

        # status filtering: drafts are invisible to matching unless asked for
        data[0]["status"] = "draft"
        qa_engine.save_qa_data(data)
        match, score = qa_engine.find_best_answer("Which camera do you use?")
        assert match is None, "draft record leaked into matching"
        match, score = qa_engine.find_best_answer(
            "Which camera do you use?", include_drafts=True
        )
        assert match and score == 1.0
        data[0]["status"] = "approved"
        qa_engine.save_qa_data(data)

        # mark_used persists usage_count and last_used_at
        used = qa_engine.mark_used(data[0]["id"])
        assert used["usage_count"] == 1 and used["last_used_at"]
        assert qa_engine.load_qa_data()[0]["usage_count"] == 1

        # delete
        assert qa_engine.delete_record(data[0]["id"]) is True
        assert qa_engine.load_qa_data() == []

        # phase 1 migration: old flat pairs load as v2
        qa_engine.QA_FILE.write_text(
            json.dumps([{"question": "which lens?", "answer": "16mm f1.4"}]),
            encoding="utf-8",
        )
        migrated = qa_engine.load_qa_data()
        assert len(migrated) == 1
        assert migrated[0]["normalized_question"] == "which lens"
        assert migrated[0]["answer_text"] == "16mm f1.4"
        assert migrated[0]["original_question_examples"] == ["which lens?"]

        # corrupt file: parked for recovery, not silently wiped
        qa_engine.QA_FILE.write_text("{broken", encoding="utf-8")
        assert qa_engine.load_qa_data() == []
        assert list(Path(tmp).glob("*.corrupt-*")), "corrupt file not parked"

        # validation
        for bad in [("", "x"), ("q", "")]:
            try:
                qa_engine.add_question_answer(*bad)
                raise AssertionError("empty input accepted")
            except ValueError:
                pass

    print("test_qa_engine: all checks passed")


if __name__ == "__main__":
    check()
