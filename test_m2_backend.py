import sys
from pathlib import Path
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from backend.main import app
from backend.deps import session_store
from backend.models import UserSessionModel

client = TestClient(app)

def run_tests():
    res_health = client.get("/health")
    assert res_health.status_code == 200

    res_me = client.get("/api/me")
    assert res_me.status_code == 401

    res_state = client.get("/api/channel/UC_TEST/state")
    assert res_state.status_code == 401

    test_token = "valid_m2_test_token"
    session_store[test_token] = UserSessionModel(
        user_id="user_123",
        selected_channel_id="UC_TEST",
        verified_channels=["UC_TEST"]
    )

    res_auth_me = client.get("/api/me", headers={"x-session-token": test_token})
    assert res_auth_me.status_code == 200

    # Two-User Data Isolation: User A cannot access or alter User B's channel data (HTTP 403 Forbidden)
    test_token_user_a = "token_user_a"
    session_store[test_token_user_a] = UserSessionModel(
        user_id="user_a_id",
        selected_channel_id="UC_USER_A",
        verified_channels=["UC_USER_A"],
        has_write_scope=True
    )

    session_store["token_user_b"] = UserSessionModel(
        user_id="user_b_id",
        selected_channel_id="UC_USER_B",
        verified_channels=["UC_USER_B"],
        has_write_scope=True
    )

    # User A tries to access User B's channel endpoint -> 403 Forbidden
    res_cross_access = client.post(
        "/api/channel/UC_USER_B/post",
        headers={"x-session-token": test_token_user_a},
        json={"answer_text": "Unauthorized write", "live_chat_id": "chat_user_b"}
    )
    assert res_cross_access.status_code == 403
    assert "not authorized for this user session" in res_cross_access.json()["detail"]

    # User A accesses their own endpoint targeting an external stream -> 200 OK
    res_ext_stream = client.post(
        "/api/channel/UC_USER_A/post",
        headers={"x-session-token": test_token_user_a},
        json={"answer_text": "Hello stream", "live_chat_id": "mock_chat_ext_123"}
    )
    assert res_ext_stream.status_code == 200
    assert res_ext_stream.json()["status"] == "posted"
    assert res_ext_stream.json()["live_chat_id"] == "mock_chat_ext_123"

    test_channel_id_mismatch_regression()
    test_mock_message_id_bypass_regression()
    test_youtube_403_sanitized_error_handling()

    print("test_m2_backend: all checks passed")

def test_channel_id_mismatch_regression():
    from backend import storage, routes, auth
    import live_chat_poller as poller
    import qa_engine

    auth_app_channel_id = "UC_AUTHORIZED_APP_123"
    public_stream_channel_id = "UC_PUBLIC_STREAM_EXT_456"
    
    # 1. Setup session with authorized app channel ID
    token = "token_reg_mismatch"
    session_store[token] = UserSessionModel(
        user_id="user_reg_mismatch",
        selected_channel_id=auth_app_channel_id,
        verified_channels=[auth_app_channel_id],
        has_write_scope=True
    )

    # 2. Setup pending question under authorized app channel ID, linked to external stream's live chat
    pending_path = storage.get_pending_path(auth_app_channel_id)
    pending_data = {
        "what camera u using?": {
            "key": "what camera u using?",
            "examples": ["what camera u using?"],
            "count": 1,
            "first_seen": "2026-10-01T00:00:00Z",
            "last_seen": "2026-10-01T00:00:00Z",
            "status": "pending",
            "posted_message_id": None,
            "error": None,
            "occurrences": [
                {
                    "occurrence_id": "occ_ext_1",
                    "live_chat_id": "real_live_chat_ext_999",
                    "author_name": "Viewer1",
                    "timestamp": "2026-10-01T00:00:00Z"
                }
            ]
        }
    }
    qa_engine.atomic_write_json(pending_path, pending_data)

    class DummySuccess:
        status_code = 200
        def json(self):
            return {"id": "yt_msg_mismatch_pass", "snippet": {"liveChatId": "real_live_chat_ext_999"}}

    routes.requests.post = lambda url, *a, **kw: DummySuccess()
    routes.auth.load_user_tokens = lambda uid, cid: {"access_token": "valid_real_token", "refresh_token": "ref_token"}

    # 3. Assert direct request using public_stream_channel_id returns 403 Forbidden
    res_direct = client.post(
        f"/api/channel/{public_stream_channel_id}/post",
        headers={"x-session-token": token},
        json={
            "answer_text": "Sony A7IV",
            "question_key": "what camera u using?",
            "occurrence_id": "occ_ext_1"
        }
    )
    assert res_direct.status_code == 403
    assert f"Channel {public_stream_channel_id!r} is not authorized for this user session." in res_direct.json()["detail"]

    # 4. Save & post now calls route under authorized app channel ID
    res_post = client.post(
        f"/api/channel/{auth_app_channel_id}/post",
        headers={"x-session-token": token},
        json={
            "answer_text": "Sony A7IV",
            "question_key": "what camera u using?",
            "occurrence_id": "occ_ext_1"
        }
    )
    assert res_post.status_code == 200
    assert res_post.json()["status"] == "posted"
    assert res_post.json()["live_chat_id"] == "real_live_chat_ext_999"

    # 5. Assert posting state stays isolated under authorized app channel
    auth_pending = poller.load_pending(channel_id=auth_app_channel_id)
    assert "what camera u using?" not in auth_pending

    auth_qa = qa_engine.load_qa_data(channel_id=auth_app_channel_id)
    assert any(q.get("answer_text") == "Sony A7IV" for q in auth_qa)

    pub_pending = poller.load_pending(channel_id=public_stream_channel_id)
    assert pub_pending == {}

    pub_qa = qa_engine.load_qa_data(channel_id=public_stream_channel_id)
    assert pub_qa == []

    print("test_channel_id_mismatch_regression passed")

def test_mock_message_id_bypass_regression():
    from backend import storage, routes, auth
    import live_chat_poller as poller
    import qa_engine

    auth_app_channel_id = "UC_AUTHORIZED_APP_MOCK_TEST"
    token = "token_mock_msg_test"
    session_store[token] = UserSessionModel(
        user_id="user_mock_msg_test",
        selected_channel_id=auth_app_channel_id,
        verified_channels=[auth_app_channel_id],
        has_write_scope=True
    )

    pending_path = storage.get_pending_path(auth_app_channel_id)
    pending_data = {
        "is this a mock question": {
            "key": "is this a mock question",
            "examples": ["is this a mock question?"],
            "count": 1,
            "first_seen": "2026-10-01T00:00:00Z",
            "last_seen": "2026-10-01T00:00:00Z",
            "status": "pending",
            "posted_message_id": None,
            "error": None,
            "occurrences": [
                {
                    "occurrence_id": "occ_mock_123",
                    "message_id": "msg_mock_1790795406690",
                    "live_chat_id": "real_yt_chat_id_xyz",
                    "author_name": "MockUser",
                    "timestamp": "2026-10-01T00:00:00Z"
                }
            ]
        }
    }
    qa_engine.atomic_write_json(pending_path, pending_data)

    class DummySuccess:
        status_code = 200
        def json(self):
            return {"id": "yt_msg_mock_src_posted", "snippet": {"liveChatId": "real_yt_chat_id_xyz"}}

    routes.requests.post = lambda url, *a, **kw: DummySuccess()
    routes.auth.load_user_tokens = lambda uid, cid: {"access_token": "valid_real_token", "refresh_token": "ref_token"}

    res_post = client.post(
        f"/api/channel/{auth_app_channel_id}/post",
        headers={"x-session-token": token},
        json={
            "answer_text": "Yes mock answer",
            "question_key": "is this a mock question",
            "occurrence_id": "occ_mock_123"
        }
    )
    assert res_post.status_code == 200
    assert res_post.json()["status"] == "posted"
    assert res_post.json()["youtube_message_id"] == "yt_msg_mock_src_posted"

    auth_pending = poller.load_pending(channel_id=auth_app_channel_id)
    assert "is this a mock question" not in auth_pending

    print("test_mock_message_id_bypass_regression passed")


def test_youtube_403_sanitized_error_handling():
    from backend import storage, routes
    import requests
    import qa_engine
    import live_chat_poller as poller

    auth_app_channel_id = "UC_AUTHORIZED_APP_YT403"
    token = "token_yt403_test"
    session_store[token] = UserSessionModel(
        user_id="user_yt403_test",
        selected_channel_id=auth_app_channel_id,
        verified_channels=[auth_app_channel_id],
        has_write_scope=True
    )

    pending_path = storage.get_pending_path(auth_app_channel_id)
    pending_data = {
        "real stream question": {
            "key": "real stream question",
            "examples": ["real stream question?"],
            "count": 1,
            "first_seen": "2026-10-01T00:00:00Z",
            "last_seen": "2026-10-01T00:00:00Z",
            "status": "pending",
            "posted_message_id": None,
            "error": None,
            "occurrences": [
                {
                    "occurrence_id": "occ_real_1",
                    "message_id": "yt_msg_real_999",
                    "live_chat_id": "real_live_chat_111",
                    "author_name": "RealUser",
                    "timestamp": "2026-10-01T00:00:00Z"
                }
            ]
        }
    }
    qa_engine.atomic_write_json(pending_path, pending_data)

    class Mock403Response:
        status_code = 403
        text = '{"error": {"code": 403, "message": "The user is not authorized to post in this live chat.", "errors": [{"reason": "liveChatEnded"}]}}'
        def json(self):
            import json
            return json.loads(self.text)

    original_post = requests.post
    def mock_requests_post(url, *args, **kwargs):
        if "google" in url or "youtube" in url:
            return Mock403Response()
        return original_post(url, *args, **kwargs)

    routes.requests.post = mock_requests_post
    routes.auth.load_user_tokens = lambda uid, cid: {"access_token": "valid_real_oauth_token", "refresh_token": "ref_token"}

    try:
        res_post = client.post(
            f"/api/channel/{auth_app_channel_id}/post",
            headers={"x-session-token": token},
            json={
                "answer_text": "Real answer",
                "question_key": "real stream question",
                "occurrence_id": "occ_real_1"
            }
        )
        assert res_post.status_code == 400
        assert "Live chat is disabled or ended." in res_post.json()["detail"]

        pending_after = poller.load_pending(channel_id=auth_app_channel_id)
        assert pending_after["real stream question"]["status"] == "failed"
        assert pending_after["real stream question"]["error"] == "Live chat is disabled or ended."
    finally:
        routes.requests.post = original_post

    print("test_youtube_403_sanitized_error_handling passed")

if __name__ == "__main__":
    run_tests()
