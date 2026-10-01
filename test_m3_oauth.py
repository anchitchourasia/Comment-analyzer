import sys
import tempfile
import json
import os
import urllib.parse
from pathlib import Path
from fastapi.testclient import TestClient

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from backend import auth, routes, storage, oauth_config
import qa_engine
from backend.main import app
from backend.deps import session_store
from backend.models import UserSessionModel

client = TestClient(app, follow_redirects=False)

def run_tests():
    orig_data_dir = storage.DATA_DIR
    orig_client_id = os.environ.get("GOOGLE_CLIENT_ID")
    orig_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        test_data_dir = temp_dir / "data"
        storage.DATA_DIR = test_data_dir
        auth.USERS_DIR = test_data_dir / "users"

        # --- Test 1: Fernet token encryption & decryption round-trip ---
        raw_tokens = {"access_token": "secret_access_123", "refresh_token": "secret_refresh_456", "channel_id": "UC_TEST"}
        enc_bytes = auth.encrypt_tokens(raw_tokens)
        assert isinstance(enc_bytes, bytes)
        assert enc_bytes != json.dumps(raw_tokens).encode("utf-8")  # Encrypted, not plaintext!
        decrypted = auth.decrypt_tokens(enc_bytes)
        assert decrypted == raw_tokens

        # --- Test 2: Unconfigured / Placeholder credentials fail closed (503) ---
        os.environ["GOOGLE_CLIENT_ID"] = "mock-client-id"
        os.environ["GOOGLE_CLIENT_SECRET"] = "mock-client-secret"
        
        res_unconf_login = client.get("/api/auth/login/init")
        assert res_unconf_login.status_code == 503
        assert res_unconf_login.json()["detail"] == "Google login not configured"

        # --- Test 3: Valid Credentials generate exact backend callback URIs & scopes ---
        os.environ["GOOGLE_CLIENT_ID"] = "test_valid_client_id_123.apps.googleusercontent.com"
        os.environ["GOOGLE_CLIENT_SECRET"] = "test_valid_client_secret_xyz"

        res_login_init = client.get("/api/auth/login/init")
        assert res_login_init.status_code == 200
        login_init_data = res_login_init.json()
        assert "auth_url" in login_init_data
        assert "state" in login_init_data
        
        # Verify exact login redirect_uri & scopes
        parsed_login_url = urllib.parse.urlparse(login_init_data["auth_url"])
        query_params = urllib.parse.parse_qs(parsed_login_url.query)
        assert query_params["redirect_uri"][0] == "http://localhost:8000/api/auth/login/callback"
        assert query_params["client_id"][0] == "test_valid_client_id_123.apps.googleusercontent.com"
        assert "youtube.force-ssl" in query_params["scope"][0]
        assert "openid" in query_params["scope"][0]

        login_state = login_init_data["state"]

        # --- Test 4: Single Callback & Identity/Channel Mapping (No raw auth codes or secrets in /api/me) ---
        res_browser_cb = client.get(f"/api/auth/login/callback?code=test_code_single&state={login_state}")
        assert res_browser_cb.status_code == 303
        location_hdr = res_browser_cb.headers.get("location")
        assert location_hdr == "http://localhost:8501/"  # Clean redirect, ZERO credentials or tokens in URL!
        assert "session_token" not in location_hdr
        assert "access_token" not in location_hdr
        assert "code" not in location_hdr

        # Verify HttpOnly session cookie was set
        set_cookie_hdr = res_browser_cb.headers.get("set-cookie")
        assert "session=" in set_cookie_hdr
        assert "httponly" in set_cookie_hdr.lower()

        # Extract session token from cookie & test /api/me response
        session_token_1 = res_browser_cb.cookies.get("session")
        assert session_token_1 in session_store

        me_res = client.get("/api/me", cookies={"session": session_token_1})
        assert me_res.status_code == 200
        me_data = me_res.json()

        assert me_data["account_label"] == "testuser@example.com"
        assert me_data["user_email"] == "testuser@example.com"
        assert me_data["user_name"] == "Test User"
        assert me_data["selected_channel_id"] == "UC_TEST_FIXTURE_123"
        assert me_data["selected_channel_title"] == "Test Streamer Channel"
        assert me_data["channel_connection_status"] == "connected"

        # Assert zero tokens or raw code values in /api/me response payload
        me_json_str = json.dumps(me_data)
        assert "access_token" not in me_json_str
        assert "refresh_token" not in me_json_str
        assert "client_secret" not in me_json_str
        assert "test_code_single" not in me_json_str
        assert "sub_test_code_single" not in me_json_str

        # --- Test 5: Idempotency & Reused/Expired Callback State Guard ---
        res_reused_cb = client.get(f"/api/auth/login/callback?code=test_code_single&state={login_state}")
        assert res_reused_cb.status_code == 303
        assert res_reused_cb.headers.get("location") == "http://localhost:8501/?auth_error=invalid_state"

        # --- Test 6: Zero Channels ("no_channels") Handling ---
        res_init_none = client.get("/api/auth/login/init")
        state_none = res_init_none.json()["state"]
        res_cb_none = client.get(f"/api/auth/login/callback?code=test_code_none&state={state_none}")
        assert res_cb_none.status_code == 303
        s_none = res_cb_none.cookies.get("session")
        
        me_none = client.get("/api/me", cookies={"session": s_none}).json()
        assert me_none["account_label"] == "nochanuser@example.com"
        assert me_none["selected_channel_id"] is None
        assert me_none["channel_connection_status"] == "no_channels"

        # --- Test 7: YouTube API Error ("api_error") Handling ---
        res_init_err = client.get("/api/auth/login/init")
        state_err = res_init_err.json()["state"]
        res_cb_err = client.get(f"/api/auth/login/callback?code=test_code_api_error&state={state_err}")
        assert res_cb_err.status_code == 303
        s_err = res_cb_err.cookies.get("session")
        
        me_err = client.get("/api/me", cookies={"session": s_err}).json()
        assert me_err["selected_channel_id"] is None
        assert me_err["channel_connection_status"] == "api_error"

        # --- Test 8: Multi-channel & Stale Session Replacement ---
        res_init_multi = client.get("/api/auth/login/init")
        state_multi = res_init_multi.json()["state"]
        res_cb_multi = client.get(f"/api/auth/login/callback?code=test_code_multi&state={state_multi}")
        s_multi = res_cb_multi.cookies.get("session")
        
        # Initially 2 channels discovered, no channel auto-selected yet
        me_multi = client.get("/api/me", cookies={"session": s_multi}).json()
        assert me_multi["selected_channel_id"] is None

        # User selects UC_MULTI_2
        res_select = client.post("/api/oauth/select_channel", cookies={"session": s_multi}, json={"channel_id": "UC_MULTI_2"})
        assert res_select.status_code == 200

        me_multi_after = client.get("/api/me", cookies={"session": s_multi}).json()
        assert me_multi_after["selected_channel_id"] == "UC_MULTI_2"
        assert me_multi_after["selected_channel_title"] == "Streamer Channel 2"

        # User 1 posts to their channel
        res_u1_post = client.post("/api/channel/UC_TEST_FIXTURE_123/post", cookies={"session": session_token_1}, json={"answer_text": "Hi", "live_chat_id": "c1"})
        assert res_u1_post.status_code == 200

        # User 1 cannot access User 2's channel endpoint directly (403 Forbidden data isolation guard)
        res_u1_to_u2 = client.post("/api/channel/UC_MULTI_2/post", cookies={"session": session_token_1}, json={"answer_text": "Unauthorized data access", "live_chat_id": "c2"})
        assert res_u1_to_u2.status_code == 403
        assert "not authorized for this user session" in res_u1_to_u2.json()["detail"]

        # --- Test 9: Client-supplied live_chat_id Override Guard & Stored Resolution ---
        from live_chat_poller import upsert_pending, load_pending, PENDING_LOCK
        q_key = upsert_pending("How to start the app?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_stored_123", message_id="msg_original_777", author_name="Viewer1")
        assert q_key is not None

        # Client attempts to supply a fake live_chat_id "fake_chat_999"
        res_post_fake = client.post(
            "/api/channel/UC_TEST_FIXTURE_123/post",
            cookies={"session": session_token_1},
            json={
                "answer_text": "Follow setup guide",
                "question_key": q_key,
                "live_chat_id": "fake_chat_999"
            }
        )
        assert res_post_fake.status_code == 200
        # Authoritative backend post used chat_stored_123 (from occurrence), ignoring fake_chat_999!
        assert res_post_fake.json()["live_chat_id"] == "chat_stored_123"

        # --- Test 10: Manual/Auto-Reply Race & Double-Click Conflict (HTTP 409) ---
        q_key_race = upsert_pending("What is the cost?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_stored_123", message_id="msg_race_1")
        
        # Manually set status to "in_flight" to simulate a concurrent post in progress
        with PENDING_LOCK:
            pending_db = load_pending(channel_id="UC_TEST_FIXTURE_123")
            pending_db[q_key_race]["status"] = "in_flight"
            storage.get_pending_path("UC_TEST_FIXTURE_123").write_text(json.dumps(pending_db), encoding="utf-8")

        res_race_post = client.post(
            "/api/channel/UC_TEST_FIXTURE_123/post",
            cookies={"session": session_token_1},
            json={"answer_text": "Free tier available", "question_key": q_key_race}
        )
        assert res_race_post.status_code == 409
        assert "already in progress" in res_race_post.json()["detail"]

        # --- Test 11: Timeout Outcome Unknown & Retry Blockage (HTTP 409) ---
        q_key_timeout = upsert_pending("Is there support?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_stored_123", message_id="msg_timeout_1")
        with PENDING_LOCK:
            pending_db = load_pending(channel_id="UC_TEST_FIXTURE_123")
            pending_db[q_key_timeout]["status"] = "outcome_unknown"
            storage.get_pending_path("UC_TEST_FIXTURE_123").write_text(json.dumps(pending_db), encoding="utf-8")

        res_timeout_retry = client.post(
            "/api/channel/UC_TEST_FIXTURE_123/post",
            cookies={"session": session_token_1},
            json={"answer_text": "Yes 24/7", "question_key": q_key_timeout}
        )
        assert res_timeout_retry.status_code == 409
        assert "Delivery outcome is unknown" in res_timeout_retry.json()["detail"]

        # --- Test 13: Grouped Questions Occurrence Selection ---
        # Ask same question twice with different occurrences
        q_key_grp = upsert_pending("How do I update?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_occ1", message_id="msg_occ1", author_name="ViewerAlpha")
        upsert_pending("How do I update?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_occ2", message_id="msg_occ2", author_name="ViewerBeta")
        
        pending_grp = load_pending(channel_id="UC_TEST_FIXTURE_123")[q_key_grp]
        assert len(pending_grp["occurrences"]) == 2
        occ_target = pending_grp["occurrences"][0]  # most recent occurrence
        
        res_post_grp = client.post(
            "/api/channel/UC_TEST_FIXTURE_123/post",
            cookies={"session": session_token_1},
            json={
                "answer_text": "Click update button",
                "question_key": q_key_grp,
                "occurrence_id": occ_target["occurrence_id"]
            }
        )
        assert res_post_grp.status_code == 200
        assert res_post_grp.json()["live_chat_id"] == occ_target["live_chat_id"]

        # --- Test 14: Inter-Process File Lock Guard ---
        test_file_path = storage.get_pending_path("UC_TEST_FIXTURE_123")
        with storage.interprocess_file_lock(test_file_path):
            # Inside lock, attempt to acquire lock again in same thread (re-entrant check)
            with storage.interprocess_file_lock(test_file_path):
                pass
        # Lock freed cleanly

        # --- Test 15: Restart Recovery Guard ---
        # Save pending item with status 'outcome_unknown'
        q_key_restart = upsert_pending("Does state persist?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_stored_123", message_id="msg_rest_1")
        with PENDING_LOCK:
            with storage.interprocess_file_lock(test_file_path):
                pdb = load_pending(channel_id="UC_TEST_FIXTURE_123")
                pdb[q_key_restart]["status"] = "outcome_unknown"
                qa_engine.atomic_write_json(test_file_path, pdb)

        # Reload pending from disk (simulating restart)
        reloaded_db = load_pending(channel_id="UC_TEST_FIXTURE_123")
        assert reloaded_db[q_key_restart]["status"] == "outcome_unknown"

        # --- Test 17: Granted Scope Verification (Read-Only vs Write Permission) ---
        res_init_ro = client.get("/api/auth/login/init")
        state_ro = res_init_ro.json()["state"]
        res_cb_ro = client.get(f"/api/auth/login/callback?code=test_code_readonly&state={state_ro}")
        assert res_cb_ro.status_code == 303
        s_ro = res_cb_ro.cookies.get("session")
        
        me_ro = client.get("/api/me", cookies={"session": s_ro}).json()
        assert me_ro["has_write_scope"] is False
        assert me_ro["channel_connection_status"] == "missing_write_scope"

        # Attempting to post with read-only scope fails with HTTP 403 Forbidden
        res_post_ro = client.post(
            "/api/channel/UC_READONLY_123/post",
            cookies={"session": s_ro},
            json={"answer_text": "Trying to post", "live_chat_id": "chat_ro_123"}
        )
        assert res_post_ro.status_code == 403
        assert "requires write authorization" in res_post_ro.json()["detail"]

        # --- Test 18: Button-to-Backend Mocked Insert Execution ---
        q_key_btn = upsert_pending("How do I start?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_btn_123", message_id="msg_btn_1")
        res_btn_post = client.post(
            "/api/channel/UC_TEST_FIXTURE_123/post",
            cookies={"session": session_token_1},
            json={
                "answer_text": "Run python main.py",
                "question_key": q_key_btn,
                "auto_reply_opt_in": True
            }
        )
        assert res_btn_post.status_code == 200
        btn_data = res_btn_post.json()
        assert btn_data["status"] == "posted"
        assert btn_data["message"] == "Posted to the live chat"
        assert btn_data["live_chat_id"] == "chat_btn_123"
        assert btn_data["youtube_message_id"].startswith("LCMC_mock_")

        # --- Test 19: External Stream Posting (User A posts to external stream chat_channel_b_999 via User A's authorized endpoint) ---
        q_key_mod = upsert_pending("Can User A post to external stream?", channel_id="UC_TEST_FIXTURE_123", live_chat_id="chat_channel_b_999", message_id="msg_mod_1")
        res_mod_post = client.post(
            "/api/channel/UC_TEST_FIXTURE_123/post",
            cookies={"session": session_token_1},
            json={
                "answer_text": "Yes, User A posts to external stream!",
                "question_key": q_key_mod
            }
        )
        assert res_mod_post.status_code == 200
        mod_data = res_mod_post.json()
        assert mod_data["status"] == "posted"
        assert mod_data["live_chat_id"] == "chat_channel_b_999"

        # --- Test 12: Logout Clears Session ---
        res_logout = client.post("/api/auth/logout", cookies={"session": session_token_1})
        assert res_logout.status_code == 200
        assert session_token_1 not in session_store

        # --- Test 16: Production Code Repository Guard ---
        # Fails if UC_OAUTH_VERIFIED_123, Streamer Channel 123, or @streamer123 appear in production code
        prod_files = [
            BASE_DIR / "backend" / "routes.py",
            BASE_DIR / "backend" / "models.py",
            BASE_DIR / "backend" / "auth.py",
            BASE_DIR / "backend" / "deps.py",
            BASE_DIR / "streamlit_app.py"
        ]
        forbidden_placeholders = ["UC_OAUTH_VERIFIED_123", "Streamer Channel 123", "@streamer123"]
        for pfile in prod_files:
            if pfile.exists():
                content = pfile.read_text(encoding="utf-8")
                for placeholder in forbidden_placeholders:
                    assert placeholder not in content, f"Forbidden production placeholder '{placeholder}' found in {pfile}"

    # Restore environment
    if orig_client_id is not None:
        os.environ["GOOGLE_CLIENT_ID"] = orig_client_id
    else:
        os.environ.pop("GOOGLE_CLIENT_ID", None)

    if orig_client_secret is not None:
        os.environ["GOOGLE_CLIENT_SECRET"] = orig_client_secret
    else:
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)

    storage.DATA_DIR = orig_data_dir
    print("test_m3_oauth: all checks passed (including production code guard & privacy assertions)")

if __name__ == "__main__":
    run_tests()


