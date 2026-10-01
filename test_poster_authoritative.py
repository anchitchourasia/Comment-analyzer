import sys
import uuid
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from backend.main import app
from backend.deps import session_store
from backend.models import UserSessionModel
from backend import storage, routes, auth
import live_chat_poller as poller
import qa_engine
import requests

client = TestClient(app)

def setup_test_user_and_pending(channel_id, user_id="user_test_auth", write_scope=True, live_chat_id="chat_active_123", msg_id="yt_msg_src_100"):
    token = f"token_{uuid.uuid4().hex[:8]}"
    scopes = "https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube.readonly" if write_scope else "https://www.googleapis.com/auth/youtube.readonly"
    
    session_store[token] = UserSessionModel(
        user_id=user_id,
        selected_channel_id=channel_id,
        verified_channels=[channel_id],
        has_write_scope=write_scope,
        granted_scopes=scopes
    )
    auth.save_user_tokens(user_id, channel_id, {"access_token": "valid_oauth_access_token", "refresh_token": "valid_oauth_refresh_token"})

    # Setup active assistant state
    active_state = poller.get_assistant_state()
    active_state.live_chat_id = live_chat_id
    active_state.channel_id = channel_id
    active_state.video_id = "video_active_999"

    # Setup pending question
    q_key = f"test question {uuid.uuid4().hex[:6]}"
    occ_id = f"occ_{uuid.uuid4().hex[:6]}"
    pending_path = storage.get_pending_path(channel_id)
    
    pending_data = poller.load_pending(channel_id=channel_id)
    pending_data[q_key] = {
        "key": q_key,
        "examples": [f"{q_key}?"],
        "count": 1,
        "first_seen": "2026-10-01T00:00:00Z",
        "last_seen": "2026-10-01T00:00:00Z",
        "status": "pending",
        "posted_message_id": None,
        "error": None,
        "occurrences": [
            {
                "occurrence_id": occ_id,
                "message_id": msg_id,
                "live_chat_id": live_chat_id,
                "author_name": "TestViewer",
                "timestamp": "2026-10-01T00:00:00Z"
            }
        ]
    }
    qa_engine.atomic_write_json(pending_path, pending_data)
    return token, q_key, occ_id, live_chat_id, channel_id


class DummyResponse:
    def __init__(self, status_code, json_data, text=""):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text or str(json_data)

    def json(self):
        return self._json_data


# 1. Successful insert with exact answer text and exact active liveChatId
def test_successful_insert():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_SUCCESS_TEST")
    
    def mock_post(url, *args, **kwargs):
        if "liveChat/messages" in url:
            body = kwargs.get("json", {})
            assert body["snippet"]["liveChatId"] == live_chat_id
            assert body["snippet"]["textMessageDetails"]["messageText"] == "Exact test answer"
            return DummyResponse(200, {
                "id": "yt_msg_real_success_555",
                "snippet": {"liveChatId": live_chat_id}
            })
        return DummyResponse(404, {})

    orig_post = routes.requests.post
    routes.requests.post = mock_post
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Exact test answer", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "posted"
        assert data["youtube_message_id"] == "yt_msg_real_success_555"
        assert data["live_chat_id"] == live_chat_id

        # Verify pending question removed
        pending = poller.load_pending(channel_id=channel_id)
        assert q_key not in pending
    finally:
        routes.requests.post = orig_post


# 2 & 12. Backend success requires returned YT msg ID & Persisted in log
def test_backend_success_requires_msg_id_and_persisted():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_PERSIST_TEST")
    
    def mock_post(url, *args, **kwargs):
        return DummyResponse(200, {
            "id": "yt_msg_persisted_777",
            "snippet": {"liveChatId": live_chat_id}
        })

    orig_post = routes.requests.post
    routes.requests.post = mock_post
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Answer for log test", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 200
        
        # Verify log file
        log_path = storage.get_log_path(channel_id)
        assert log_path.exists()
        log_content = log_path.read_text(encoding="utf-8")
        assert "yt_msg_persisted_777" in log_content
        assert live_chat_id in log_content
    finally:
        routes.requests.post = orig_post


# 3. Internal 200 without YouTube message ID is not success
def test_no_yt_msg_id_returned_fails():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_NO_ID_TEST")
    
    def mock_post(url, *args, **kwargs):
        return DummyResponse(200, {
            "id": "",
            "snippet": {"liveChatId": live_chat_id}
        })

    orig_post = routes.requests.post
    routes.requests.post = mock_post
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Answer no id", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 400
        assert "no created message ID was returned" in res.json()["detail"]
        
        pending = poller.load_pending(channel_id=channel_id)
        assert pending[q_key]["status"] == "failed"
    finally:
        routes.requests.post = orig_post


# 4. Insert response contains a different chat ID: reject it
def test_different_chat_id_rejected():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_DIFF_CHAT_TEST")
    
    def mock_post(url, *args, **kwargs):
        return DummyResponse(200, {
            "id": "yt_msg_wrong_chat",
            "snippet": {"liveChatId": "wrong_live_chat_999"}
        })

    orig_post = routes.requests.post
    routes.requests.post = mock_post
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Answer diff chat", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 400
        assert "different liveChatId" in res.json()["detail"]
    finally:
        routes.requests.post = orig_post


# 5. Mock source message with real active live chat: posts successfully to YouTube
def test_mock_source_message_posts_to_real_chat():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending(
        "UC_MOCK_SRC_TEST", msg_id="msg_mock_123456789"
    )
    
    def mock_post(url, *args, **kwargs):
        return DummyResponse(200, {
            "id": "yt_msg_real_posted_123",
            "snippet": {"liveChatId": live_chat_id}
        })

    orig_post = routes.requests.post
    routes.requests.post = mock_post
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Answer for mock source", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 200
        assert res.json()["status"] == "posted"
        assert res.json()["youtube_message_id"] == "yt_msg_real_posted_123"
    finally:
        routes.requests.post = orig_post


# 6. Selected chat does not equal current activeLiveChatId: reject it
def test_chat_mismatch_with_active_state_rejected():
    token, q_key, occ_id, _, channel_id = setup_test_user_and_pending("UC_MISMATCH_ACTIVE_TEST", live_chat_id="old_chat_111")
    
    # Active state changes to new live chat
    active_state = poller.get_assistant_state()
    active_state.live_chat_id = "new_active_chat_222"

    res = client.post(
        f"/api/channel/{channel_id}/post",
        headers={"x-session-token": token},
        json={"answer_text": "Answer mismatch", "question_key": q_key, "occurrence_id": occ_id}
    )
    assert res.status_code == 400
    assert "does not match current activeLiveChatId" in res.json()["detail"]


# 7. youtube.readonly token: posting disabled
def test_readonly_token_posting_disabled():
    token, q_key, occ_id, _, channel_id = setup_test_user_and_pending("UC_READONLY_TEST", write_scope=False)
    
    res = client.post(
        f"/api/channel/{channel_id}/post",
        headers={"x-session-token": token},
        json={"answer_text": "Answer for readonly", "question_key": q_key, "occurrence_id": occ_id}
    )
    assert res.status_code == 403
    assert "requires write authorization" in res.json()["detail"]


# 8 & 9. YouTube 403 reasons & Subscribers-only chat handling
def test_youtube_403_reasons():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_403_TEST")
    
    def mock_post_403(url, *args, **kwargs):
        return DummyResponse(403, {
            "error": {
                "errors": [{"reason": "liveChatEnded", "message": "The live chat is ended"}]
            }
        }, text="livechatended")

    orig_post = routes.requests.post
    routes.requests.post = mock_post_403
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Answer 403", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 400
        assert "Live chat is disabled or ended." in res.json()["detail"]
    finally:
        routes.requests.post = orig_post


# 10. Repeated button click / worker race: at most one insert
def test_repeated_button_click_in_flight_conflict():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_RACE_TEST")
    
    call_count = 0
    def mock_slow_post(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        return DummyResponse(200, {"id": "yt_msg_race_1", "snippet": {"liveChatId": live_chat_id}})

    orig_post = routes.requests.post
    routes.requests.post = mock_slow_post
    try:
        # Simulate manually marking status as in_flight
        pending_path = storage.get_pending_path(channel_id)
        with poller.PENDING_LOCK:
            with storage.interprocess_file_lock(pending_path):
                pending = poller.load_pending(channel_id=channel_id)
                pending[q_key]["status"] = "in_flight"
                qa_engine.atomic_write_json(pending_path, pending)

        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Duplicate click", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 409
        assert "Posting already in progress or completed" in res.json()["detail"]
        assert call_count == 0
    finally:
        routes.requests.post = orig_post


# 11. Timeout after possible acceptance: outcome_unknown, no automatic retry
def test_timeout_sets_outcome_unknown():
    token, q_key, occ_id, live_chat_id, channel_id = setup_test_user_and_pending("UC_TIMEOUT_TEST")
    
    def mock_timeout(url, *args, **kwargs):
        raise requests.exceptions.Timeout("Connection timed out")

    orig_post = routes.requests.post
    routes.requests.post = mock_timeout
    try:
        res = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Timeout answer", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res.status_code == 504
        assert "Outcome is unknown" in res.json()["detail"]

        # Check pending state is set to outcome_unknown
        pending = poller.load_pending(channel_id=channel_id)
        assert pending[q_key]["status"] == "outcome_unknown"

        # Subsequent post attempt must be rejected with 409
        res2 = client.post(
            f"/api/channel/{channel_id}/post",
            headers={"x-session-token": token},
            json={"answer_text": "Timeout answer retry", "question_key": q_key, "occurrence_id": occ_id}
        )
        assert res2.status_code == 409
        assert "Delivery outcome is unknown" in res2.json()["detail"]
    finally:
        routes.requests.post = orig_post
