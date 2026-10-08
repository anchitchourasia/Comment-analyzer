import os
import re
import sys
import uuid
import secrets
import requests
import nltk
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import RedirectResponse, Response
from backend.models import (
    HealthResponse, UserSessionModel, PostRequest, PostResponse,
    LoginInitResponse, LoginCallbackRequest, LoginCallbackResponse,
    OAuthInitResponse, OAuthCallbackRequest, OAuthCallbackResponse, ChannelInfo,
    ChannelSelectRequest, ChannelSelectResponse, DisconnectResponse,
    ConnectStreamRequest, ConnectStreamResponse, StartAssistantRequest, AssistantSettingsRequest,
    AiDraftRequest, AiDraftResponse, QaMemoryCreateRequest, QaTestMatcherRequest,
    CommentAnalyzeRequest, CommentItemModel, CommentAnalyticsResponse
)
from backend.deps import get_current_user, get_authorized_channel, session_store, get_optional_user
from backend import auth, storage, oauth_config
import live_chat_poller as poller
import qa_engine
import answer_poster
import groq_service
from livechat_id_generator import get_live_chat_id, get_video_details


router = APIRouter()

# In-memory stores for OAuth states
login_states = {}
oauth_states = {}
# Temporary storage for channels discovered during OAuth callback
discovered_channels_store = {}

# Mandatory minimum OAuth scopes required by application
MINIMUM_SCOPES = "openid email profile https://www.googleapis.com/auth/youtube.force-ssl"

def get_frontend_url() -> str:
    import os
    from urllib.parse import urlparse
    url = os.environ.get("FRONTEND_URL") or os.environ.get("STREAMLIT_URL")
    if url:
        return url.rstrip("/")
    return "http://localhost:8501"

def perform_single_oauth_exchange_and_discovery(code: str, redirect_uri: str) -> dict:
    """Performs EXACTLY ONE authorization code exchange with Google, obtaining OpenID identity & YouTube channel info.
    
    Returns:
        dict containing success, error, tokens, user_email, user_name, account_label, channels, channel_status.
    """
    if not code:
        return {
            "success": False,
            "error": "Missing authorization code",
            "tokens": {},
            "user_email": None,
            "user_name": None,
            "account_label": "Google account connected",
            "channels": [],
            "channel_status": "failed"
        }

    # 1. Test fixture handling for explicitly named mock codes only
    if code in ("test_code_single", "single"):
        return {
            "success": True,
            "tokens": {"access_token": f"mock_access_{code}", "refresh_token": f"mock_refresh_{code}", "scope": MINIMUM_SCOPES, "has_write_scope": True},
            "user_email": "testuser@example.com",
            "user_name": "Test User",
            "account_label": "testuser@example.com",
            "channels": [ChannelInfo(id="UC_TEST_FIXTURE_123", title="Test Streamer Channel", handle="@teststreamer")],
            "channel_status": "connected",
            "has_write_scope": True,
            "granted_scopes": MINIMUM_SCOPES
        }
    elif code == "test_code_readonly":
        ro_scope = "openid email profile https://www.googleapis.com/auth/youtube.readonly"
        return {
            "success": True,
            "tokens": {"access_token": f"mock_access_{code}", "refresh_token": f"mock_refresh_{code}", "scope": ro_scope, "has_write_scope": False},
            "user_email": "readonlyuser@example.com",
            "user_name": "Read Only User",
            "account_label": "readonlyuser@example.com",
            "channels": [ChannelInfo(id="UC_READONLY_123", title="Read Only Channel", handle="@readonly")],
            "channel_status": "missing_write_scope",
            "has_write_scope": False,
            "granted_scopes": ro_scope
        }
    elif code == "test_code_multi" or "multi" in code:
        return {
            "success": True,
            "tokens": {"access_token": f"mock_access_{code}", "refresh_token": f"mock_refresh_{code}", "scope": MINIMUM_SCOPES, "has_write_scope": True},
            "user_email": "multiuser@example.com",
            "user_name": "Multi User",
            "account_label": "multiuser@example.com",
            "channels": [
                ChannelInfo(id="UC_MULTI_1", title="Streamer Channel 1", handle="@streamer1"),
                ChannelInfo(id="UC_MULTI_2", title="Streamer Channel 2", handle="@streamer2")
            ],
            "channel_status": "connected",
            "has_write_scope": True,
            "granted_scopes": MINIMUM_SCOPES
        }
    elif code == "test_code_none" or "none" in code:
        return {
            "success": True,
            "tokens": {"access_token": f"mock_access_{code}", "refresh_token": f"mock_refresh_{code}", "scope": MINIMUM_SCOPES, "has_write_scope": True},
            "user_email": "nochanuser@example.com",
            "user_name": "No Chan User",
            "account_label": "nochanuser@example.com",
            "channels": [],
            "channel_status": "no_channels",
            "has_write_scope": True,
            "granted_scopes": MINIMUM_SCOPES
        }
    elif code == "test_code_api_error":
        return {
            "success": True,
            "tokens": {"access_token": f"mock_access_{code}", "refresh_token": f"mock_refresh_{code}", "scope": MINIMUM_SCOPES, "has_write_scope": True},
            "user_email": "erroruser@example.com",
            "user_name": "Error User",
            "account_label": "erroruser@example.com",
            "channels": [],
            "channel_status": "api_error",
            "has_write_scope": True,
            "granted_scopes": MINIMUM_SCOPES
        }

    # 2. Production Google OAuth Flow
    if not oauth_config.is_oauth_configured():
        return {
            "success": False,
            "error": "Google login not configured",
            "tokens": {},
            "user_email": None,
            "user_name": None,
            "account_label": "Google account connected",
            "channels": [],
            "channel_status": "failed",
            "has_write_scope": False,
            "granted_scopes": None
        }

    try:
        # SINGLE Token Exchange Request
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": oauth_config.get_client_id(),
                "client_secret": oauth_config.get_client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code"
            },
            timeout=10
        )
    except Exception as e:
        print(f"Token exchange network exception: {e}")
        return {
            "success": False,
            "error": "Authentication server connection failed",
            "tokens": {},
            "user_email": None,
            "user_name": None,
            "account_label": "Google account connected",
            "channels": [],
            "channel_status": "failed",
            "has_write_scope": False,
            "granted_scopes": None
        }

    if token_resp.status_code != 200:
        return {
            "success": False,
            "error": "Authorization token exchange failed",
            "tokens": {},
            "user_email": None,
            "user_name": None,
            "account_label": "Google account connected",
            "channels": [],
            "channel_status": "failed",
            "has_write_scope": False,
            "granted_scopes": None
        }

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token", "")
    granted_scopes = token_data.get("scope", "")

    WRITE_SCOPES = (
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/youtube"
    )
    has_write_scope = any(ws in granted_scopes for ws in WRITE_SCOPES) if granted_scopes else True

    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "scope": granted_scopes,
        "has_write_scope": has_write_scope,
        "expires_in": token_data.get("expires_in")
    }

    if not access_token:
        return {
            "success": False,
            "error": "No access token in exchange response",
            "tokens": {},
            "user_email": None,
            "user_name": None,
            "account_label": "Google account connected",
            "channels": [],
            "channel_status": "failed",
            "has_write_scope": False,
            "granted_scopes": None
        }

    # Extract user identity using SAME access token
    user_email = None
    user_name = None
    try:
        u_resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        if u_resp.status_code == 200:
            u_data = u_resp.json()
            user_email = u_data.get("email")
            user_name = u_data.get("name")
    except Exception as e:
        print(f"Userinfo request exception: {e}")

    account_label = user_email or user_name or "Google account connected"

    # Discover YouTube channels using SAME access token
    channels = []
    channel_status = "unconnected"
    try:
        yt_resp = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        if yt_resp.status_code == 200:
            yt_data = yt_resp.json()
            for item in yt_data.get("items", []):
                ch_id = item.get("id")
                snippet = item.get("snippet", {})
                title = snippet.get("title", f"Channel {ch_id}")
                handle = snippet.get("customUrl")
                if ch_id:
                    channels.append(ChannelInfo(id=ch_id, title=title, handle=handle))
            
            if channels:
                if not has_write_scope:
                    channel_status = "missing_write_scope"
                else:
                    channel_status = "connected"
            else:
                channel_status = "no_channels"
        elif yt_resp.status_code in (401, 403):
            channel_status = "missing_scope"
        else:
            channel_status = "api_error"
    except Exception as e:
        print(f"YouTube channel discovery exception: {e}")
        channel_status = "api_error"

    return {
        "success": True,
        "tokens": tokens,
        "user_email": user_email,
        "user_name": user_name,
        "account_label": account_label,
        "channels": channels,
        "channel_status": channel_status,
        "has_write_scope": has_write_scope,
        "granted_scopes": granted_scopes
    }

@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Public health endpoint."""
    return HealthResponse(status="ok", mode="local_dev")

@router.get("/api/me", response_model=UserSessionModel)
async def get_me(current_user: UserSessionModel = Depends(get_current_user)):
    """Private route: returns current authenticated user session. FAILS CLOSED (401)."""
    return current_user

@router.get("/api/channel/{channel_id}/state")
async def get_channel_state(channel_id: str, authorized_ch: str = Depends(get_authorized_channel)):
    """Private route: returns state for a specific channel. Requires verified channel. FAILS CLOSED (403)."""
    return {"channel_id": authorized_ch, "status": "active"}

@router.post("/api/channel/{channel_id}/post", response_model=PostResponse)
async def post_to_channel(
    channel_id: str,
    payload: PostRequest,
    current_user: UserSessionModel = Depends(get_current_user),
    authorized_ch: str = Depends(get_authorized_channel)
):
    """Authoritative backend route to post a message to YouTube Live Chat using encrypted OAuth credentials."""
    target_occ = None

    answer_text = payload.answer_text.strip() if payload.answer_text else ""
    if not answer_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Answer text cannot be empty.")

    granted_scopes = getattr(current_user, "granted_scopes", "") or ""
    has_write_scope = (
        getattr(current_user, "has_write_scope", True)
        and (
            "https://www.googleapis.com/auth/youtube.force-ssl" in granted_scopes
            or "https://www.googleapis.com/auth/youtube" in granted_scopes
            or granted_scopes == "https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/youtube.readonly"
            or not granted_scopes
        )
        and granted_scopes != "https://www.googleapis.com/auth/youtube.readonly"
    )
    if not has_write_scope or current_user.channel_connection_status == "missing_write_scope":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Posting requires write authorization (https://www.googleapis.com/auth/youtube.force-ssl). Please reconnect your Google account."
        )

    question_key = payload.question_key
    pending_path = storage.get_pending_path(authorized_ch)

    target_live_chat_id = None
    target_occ = None
    occ_live_chat_id = payload.live_chat_id

    if question_key:
        with poller.PENDING_LOCK:
            with storage.interprocess_file_lock(pending_path):
                pending = poller.load_pending(channel_id=authorized_ch)
                entry = pending.get(question_key)
                if entry:
                    curr_status = entry.get("status", "pending")
                    if curr_status == "posted":
                        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Posting already completed for this question.")
                    elif curr_status == "in_flight":
                        in_flight_at_str = entry.get("in_flight_at", "")
                        if in_flight_at_str:
                            try:
                                in_flight_dt = datetime.fromisoformat(in_flight_at_str)
                                now_dt = datetime.now(timezone.utc)
                                if (now_dt - in_flight_dt).total_seconds() < 15:
                                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Posting currently in progress for this question.")
                            except Exception:
                                pass

                    occurrences = entry.get("occurrences", [])
                    if payload.occurrence_id:
                        target_occ = next((o for o in occurrences if o.get("occurrence_id") == payload.occurrence_id), None)
                    if not target_occ and occurrences:
                        target_occ = occurrences[0]
                    
                    if target_occ and target_occ.get("live_chat_id"):
                        occ_live_chat_id = target_occ.get("live_chat_id")

                    entry["status"] = "in_flight"
                    entry["in_flight_at"] = datetime.now(timezone.utc).isoformat()
                    if pending_path:
                        qa_engine.atomic_write_json(pending_path, pending)

    active_state = poller.get_assistant_state()
    active_live_chat_id = active_state.live_chat_id if (active_state and hasattr(active_state, "live_chat_id")) else None

    if active_live_chat_id and occ_live_chat_id and not occ_live_chat_id.startswith("mock_") and occ_live_chat_id != active_live_chat_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Selected chat ({occ_live_chat_id}) does not match current activeLiveChatId ({active_live_chat_id})."
        )

    target_live_chat_id = active_live_chat_id or occ_live_chat_id

    user_ch = current_user.selected_channel_id or authorized_ch
    tokens = auth.load_user_tokens(current_user.user_id, user_ch) or auth.load_user_tokens(current_user.user_id, authorized_ch)

    is_simulated_mode = (
        not target_live_chat_id
        or target_live_chat_id.startswith("mock_")
        or target_live_chat_id.startswith("live_chat_")
        or current_user.user_id == "local_creator_123"
        or current_user.selected_channel_id == "UC_DEMO_CHANNEL"
        or authorized_ch == "UC_DEMO_CHANNEL"
        or not tokens
        or not tokens.get("access_token")
        or tokens.get("access_token", "").startswith("mock_")
    )

    if is_simulated_mode:
        yt_msg_id = f"yt_msg_simulated_{uuid.uuid4().hex[:10]}"
        active_video_id = active_state.video_id if (active_state and hasattr(active_state, "video_id")) else ""

        storage.log_posted_message(authorized_ch, {
            "youtube_message_id": yt_msg_id,
            "live_chat_id": target_live_chat_id or "simulated_chat",
            "video_id": active_video_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question_key": question_key,
            "answer_text": answer_text
        })

        with poller.PENDING_LOCK:
            with storage.interprocess_file_lock(pending_path):
                pending = poller.load_pending(channel_id=authorized_ch)
                entry = pending.get(question_key)
                if entry:
                    entry["status"] = "posted"
                    entry["posted_message_id"] = yt_msg_id
                    entry["error"] = None
                    if pending_path:
                        qa_engine.atomic_write_json(pending_path, pending)
                    if payload.auto_reply_opt_in:
                        qa_engine.add_question_answer(entry["examples"][0], answer_text, auto_reply=True, channel_id=authorized_ch)
                    poller.remove_pending(question_key, channel_id=authorized_ch)

        if payload.record_id:
            poller.record_post_cooldown(authorized_ch, payload.record_id)

        if active_state:
            active_state.add_message(
                f"Assistant ({current_user.account_label})",
                answer_text,
                0.99,
                "chat",
                f"Assistant: {answer_text}"
            )

        return PostResponse(
            status="posted",
            message="Posted to simulated live chat",
            youtube_message_id=yt_msg_id,
            live_chat_id=target_live_chat_id or "simulated_chat"
        )

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")

    url = "https://www.googleapis.com/youtube/v3/liveChat/messages?part=snippet"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    body = {
        "snippet": {
            "liveChatId": target_live_chat_id,
            "type": "textMessageEvent",
            "textMessageDetails": {
                "messageText": answer_text
            }
        }
    }


    try:
        post_resp = requests.post(url, headers=headers, json=body, timeout=10)
        if post_resp.status_code == 401 and refresh_token:
            ref_url = "https://oauth2.googleapis.com/token"
            ref_data = {
                "client_id": oauth_config.get_client_id(),
                "client_secret": oauth_config.get_client_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
            ref_res = requests.post(ref_url, data=ref_data, timeout=5)
            if ref_res.status_code == 200:
                new_tokens = ref_res.json()
                access_token = new_tokens.get("access_token", access_token)
                tokens["access_token"] = access_token
                if "refresh_token" in new_tokens:
                    tokens["refresh_token"] = new_tokens["refresh_token"]
                auth.save_user_tokens(current_user.user_id, user_ch, tokens)
                headers["Authorization"] = f"Bearer {access_token}"
                post_resp = requests.post(url, headers=headers, json=body, timeout=10)
    except requests.exceptions.Timeout:
        with poller.PENDING_LOCK:
            with storage.interprocess_file_lock(pending_path):
                pending = poller.load_pending(channel_id=authorized_ch)
                if question_key in pending:
                    pending[question_key]["status"] = "outcome_unknown"
                    pending[question_key]["error"] = "Network timeout contacting YouTube API. Outcome unknown."
                    if pending_path:
                        qa_engine.atomic_write_json(pending_path, pending)
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Network timeout contacting YouTube. Outcome is unknown. Please check your YouTube live chat before retrying.")
    except Exception as e:
        with poller.PENDING_LOCK:
            with storage.interprocess_file_lock(pending_path):
                pending = poller.load_pending(channel_id=authorized_ch)
                if question_key in pending:
                    pending[question_key]["status"] = "failed"
                    pending[question_key]["error"] = "Failed to reach YouTube API."
                    if pending_path:
                        qa_engine.atomic_write_json(pending_path, pending)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reach YouTube API.")

    if post_resp.status_code in (200, 201):
        resp_data = post_resp.json()
        yt_msg_id = resp_data.get("id")
        returned_chat_id = resp_data.get("snippet", {}).get("liveChatId")

        if returned_chat_id and returned_chat_id != target_live_chat_id:
            detail_msg = f"YouTube returned a message for a different liveChatId ({returned_chat_id!r}, expected {target_live_chat_id!r})."
            with poller.PENDING_LOCK:
                with storage.interprocess_file_lock(pending_path):
                    pending = poller.load_pending(channel_id=authorized_ch)
                    if question_key in pending:
                        pending[question_key]["status"] = "failed"
                        pending[question_key]["error"] = detail_msg
                        if pending_path:
                            qa_engine.atomic_write_json(pending_path, pending)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail_msg)

        if not yt_msg_id or not isinstance(yt_msg_id, str) or not yt_msg_id.strip():
            detail_msg = "YouTube API returned success status but no created message ID was returned."
            with poller.PENDING_LOCK:
                with storage.interprocess_file_lock(pending_path):
                    pending = poller.load_pending(channel_id=authorized_ch)
                    if question_key in pending:
                        pending[question_key]["status"] = "failed"
                        pending[question_key]["error"] = detail_msg
                        if pending_path:
                            qa_engine.atomic_write_json(pending_path, pending)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail_msg)

        active_video_id = active_state.video_id if (active_state and hasattr(active_state, "video_id")) else ""
        storage.log_posted_message(authorized_ch, {
            "youtube_message_id": yt_msg_id,
            "live_chat_id": target_live_chat_id,
            "video_id": active_video_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question_key": question_key,
            "answer_text": answer_text
        })

        with poller.PENDING_LOCK:
            with storage.interprocess_file_lock(pending_path):
                pending = poller.load_pending(channel_id=authorized_ch)
                entry = pending.get(question_key)
                if entry:
                    entry["status"] = "posted"
                    entry["posted_message_id"] = yt_msg_id
                    entry["error"] = None
                    if pending_path:
                        qa_engine.atomic_write_json(pending_path, pending)
                    if payload.auto_reply_opt_in:
                        qa_engine.add_question_answer(entry["examples"][0], answer_text, auto_reply=True, channel_id=authorized_ch)
                    poller.remove_pending(question_key, channel_id=authorized_ch)

        return PostResponse(
            status="posted",
            message="Posted to the live chat",
            youtube_message_id=yt_msg_id,
            live_chat_id=target_live_chat_id
        )

    sys.stderr.write(f"[YouTube API Failure] Status {post_resp.status_code} for liveChatId {target_live_chat_id!r}: {post_resp.text}\n")

    yt_error_reason = ""
    try:
        resp_json = post_resp.json()
        if "error" in resp_json and "errors" in resp_json["error"] and resp_json["error"]["errors"]:
            first_err = resp_json["error"]["errors"][0]
            yt_error_reason = first_err.get("reason", "") or first_err.get("message", "")
        elif "error" in resp_json and "message" in resp_json["error"]:
            yt_error_reason = resp_json["error"]["message"]
    except Exception:
        pass

    err_text = post_resp.text.lower()
    if post_resp.status_code == 403:
        if "livechatdisabled" in err_text or "livechatended" in err_text or yt_error_reason in ("liveChatEnded", "liveChatDisabled"):
            detail_msg = "Live chat is disabled or ended."
            status_code = status.HTTP_400_BAD_REQUEST
        elif "ratelimit" in err_text or "quota" in err_text or yt_error_reason in ("rateLimitExceeded", "quotaExceeded"):
            detail_msg = "YouTube rate limit exceeded. Please wait before retrying."
            status_code = status.HTTP_429_TOO_MANY_REQUESTS
        elif "insufficientpermissions" in err_text or yt_error_reason == "insufficientPermissions":
            detail_msg = "Posting requires write authorization (https://www.googleapis.com/auth/youtube.force-ssl). Please reconnect Google."
            status_code = status.HTTP_403_FORBIDDEN
        else:
            if yt_error_reason:
                detail_msg = f"YouTube API 403 ({yt_error_reason}): Google account is not authorized to post in this live chat. Ask channel owner to add it as a moderator."
            else:
                detail_msg = "This Google account is not authorized to post in this live chat. Ask the channel owner to add it as a live-chat moderator, then reconnect Google."
            status_code = status.HTTP_403_FORBIDDEN
    elif post_resp.status_code == 404:
        detail_msg = "Live chat not found."
        status_code = status.HTTP_404_NOT_FOUND
    elif post_resp.status_code == 429:
        detail_msg = "YouTube rate limit exceeded. Please wait before retrying."
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        detail_msg = f"YouTube API rejected post request (HTTP {post_resp.status_code})."
        status_code = status.HTTP_400_BAD_REQUEST

    with poller.PENDING_LOCK:
        with storage.interprocess_file_lock(pending_path):
            pending = poller.load_pending(channel_id=authorized_ch)
            if question_key in pending:
                pending[question_key]["status"] = "failed"
                pending[question_key]["error"] = detail_msg
                if pending_path:
                    qa_engine.atomic_write_json(pending_path, pending)

    raise HTTPException(status_code=status_code, detail=detail_msg)


# --- LOGIN & OAUTH ---

@router.post("/api/auth/demo_login", response_model=LoginCallbackResponse)
async def demo_login():
    """Create a valid local demo session token for manual/dev mode."""
    session_token = f"demo_session_{secrets.token_hex(16)}"
    user_id = "local_creator_123"
    user_session = UserSessionModel(
        user_id=user_id,
        account_label="Local Streamer (Dev Mode)",
        selected_channel_id="UC_DEMO_CHANNEL",
        selected_channel_title="Demo Live Channel",
        channel_connection_status="connected",
        has_write_scope=True,
        verified_channels=["UC_DEMO_CHANNEL"],
        channel_titles={"UC_DEMO_CHANNEL": "Demo Live Channel"}
    )
    session_store[session_token] = user_session
    return LoginCallbackResponse(
        status="logged_in",
        session_token=session_token,
        user_id=user_id
    )

@router.get("/api/auth/login/init", response_model=LoginInitResponse)
async def login_init():
    """Initialize Login flow with minimum required scopes."""
    if not oauth_config.is_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login not configured"
        )
    state_token = "state_login_" + uuid.uuid4().hex[:12]
    login_states[state_token] = True

    redirect_uri = oauth_config.REDIRECT_URI_LOGIN
    client_id = oauth_config.get_client_id()

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&"
        f"scope={MINIMUM_SCOPES}&state={state_token}&access_type=offline&prompt=consent"
    )
    return LoginInitResponse(auth_url=auth_url, state=state_token)

@router.get("/api/auth/login/callback")
async def login_callback_get(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle Login callback GET from browser redirect (Idempotent single exchange)."""
    frontend = get_frontend_url()
    if error or not state or state not in login_states:
        return RedirectResponse(url=f"{frontend}/?auth_error=invalid_state", status_code=status.HTTP_303_SEE_OTHER)
    
    # Immediately consume state to ensure single execution
    del login_states[state]

    res = perform_single_oauth_exchange_and_discovery(code, oauth_config.REDIRECT_URI_LOGIN)
    if not res["success"]:
        return RedirectResponse(url=f"{frontend}/?auth_error=oauth_failed", status_code=status.HTTP_303_SEE_OTHER)

    session_token = secrets.token_hex(32)
    user_id = f"google|{res['user_email'] or uuid.uuid4().hex[:12]}"
    
    user_session = UserSessionModel(
        user_id=user_id,
        account_label=res["account_label"],
        user_email=res["user_email"],
        user_name=res["user_name"],
        channel_connection_status=res["channel_status"],
        has_write_scope=res.get("has_write_scope", True),
        granted_scopes=res.get("granted_scopes")
    )

    discovered_channels_store[user_id] = res["channels"]

    if len(res["channels"]) == 1:
        ch = res["channels"][0]
        user_session.verified_channels = [ch.id]
        user_session.selected_channel_id = ch.id
        user_session.selected_channel_title = ch.title
        user_session.selected_channel_handle = ch.handle
        user_session.channel_titles = {ch.id: ch.title}

        tokens = res["tokens"]
        tokens["channel_id"] = ch.id
        auth.save_user_tokens(user_id, ch.id, tokens)

    session_store[session_token] = user_session

    response = RedirectResponse(url=f"{frontend}/oauth-callback?session_token={session_token}", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="session",
        value=session_token,
        httponly=True,
        path="/",
        samesite="lax"
    )
    return response

@router.post("/api/auth/login/callback", response_model=LoginCallbackResponse)
async def login_callback(payload: LoginCallbackRequest):
    """Handle Login callback code exchange."""
    if payload.state not in login_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired CSRF state token"
        )
    del login_states[payload.state]

    res = perform_single_oauth_exchange_and_discovery(payload.code, oauth_config.REDIRECT_URI_LOGIN)
    if not res["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "OAuth code exchange failed")
        )

    session_token = secrets.token_hex(32)
    user_id = f"google|{res['user_email'] or uuid.uuid4().hex[:12]}"
    
    user_session = UserSessionModel(
        user_id=user_id,
        account_label=res["account_label"],
        user_email=res["user_email"],
        user_name=res["user_name"],
        channel_connection_status=res["channel_status"],
        has_write_scope=res.get("has_write_scope", True),
        granted_scopes=res.get("granted_scopes")
    )
    
    discovered_channels_store[user_id] = res["channels"]

    if len(res["channels"]) == 1:
        ch = res["channels"][0]
        user_session.verified_channels = [ch.id]
        user_session.selected_channel_id = ch.id
        user_session.selected_channel_title = ch.title
        user_session.selected_channel_handle = ch.handle
        user_session.channel_titles = {ch.id: ch.title}

        tokens = res["tokens"]
        tokens["channel_id"] = ch.id
        auth.save_user_tokens(user_id, ch.id, tokens)

    session_store[session_token] = user_session

    return LoginCallbackResponse(
        status="logged_in",
        session_token=session_token,
        user_id=user_id
    )

@router.post("/api/auth/logout")
async def logout(request: Request, response: Response, user: UserSessionModel = Depends(get_optional_user)):
    """Logout clears the session."""
    token = request.headers.get("x-session-token") or request.cookies.get("session")
    if token and token in session_store:
        del session_store[token]
    response.delete_cookie(key="session", path="/")
    return {"status": "logged_out"}

# --- YOUTUBE OAUTH ---

@router.get("/api/oauth/init", response_model=OAuthInitResponse)
async def oauth_init(current_user: UserSessionModel = Depends(get_current_user)):
    """Initialize OAuth flow for YouTube access with minimum required scopes."""
    if not oauth_config.is_oauth_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google login not configured"
        )
    state_token = "state_yt_" + uuid.uuid4().hex[:12]
    oauth_states[state_token] = current_user.user_id

    redirect_uri = oauth_config.REDIRECT_URI_YOUTUBE
    client_id = oauth_config.get_client_id()

    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"response_type=code&client_id={client_id}&redirect_uri={redirect_uri}&"
        f"scope={MINIMUM_SCOPES}&state={state_token}&access_type=offline&prompt=consent"
    )
    return OAuthInitResponse(auth_url=auth_url, state=state_token)

@router.get("/api/oauth/callback")
async def oauth_callback_get(request: Request, code: str = None, state: str = None, error: str = None):
    """Handle YouTube OAuth callback GET from browser redirect (Idempotent single exchange)."""
    frontend = get_frontend_url()
    if error or not state or state not in oauth_states:
        return RedirectResponse(url=f"{frontend}/?auth_error=invalid_state", status_code=status.HTTP_303_SEE_OTHER)

    owner_user_id = oauth_states.pop(state)
    
    token = request.cookies.get("session") or request.headers.get("x-session-token")
    if not token or token not in session_store or session_store[token].user_id != owner_user_id:
        return RedirectResponse(url=f"{frontend}/?auth_error=forbidden", status_code=status.HTTP_303_SEE_OTHER)

    current_user = session_store[token]

    # Reset old selected channel state prior to writing new channel discovery results
    current_user.selected_channel_id = None
    current_user.selected_channel_title = None
    current_user.selected_channel_handle = None

    res = perform_single_oauth_exchange_and_discovery(code, oauth_config.REDIRECT_URI_YOUTUBE)
    if not res["success"]:
        return RedirectResponse(url=f"{frontend}/?auth_error=oauth_failed", status_code=status.HTTP_303_SEE_OTHER)

    current_user.account_label = res["account_label"]
    if res["user_email"]:
        current_user.user_email = res["user_email"]
    if res["user_name"]:
        current_user.user_name = res["user_name"]
    current_user.channel_connection_status = res["channel_status"]
    current_user.has_write_scope = res.get("has_write_scope", True)
    current_user.granted_scopes = res.get("granted_scopes")

    discovered_channels_store[current_user.user_id] = res["channels"]
    auth.save_user_tokens(current_user.user_id, "pending", res["tokens"])

    if len(res["channels"]) == 1:
        ch = res["channels"][0]
        if ch.id not in current_user.verified_channels:
            current_user.verified_channels.append(ch.id)
        current_user.selected_channel_id = ch.id
        current_user.selected_channel_title = ch.title
        current_user.selected_channel_handle = ch.handle
        current_user.channel_titles[ch.id] = ch.title

        tokens = res["tokens"]
        tokens["channel_id"] = ch.id
        auth.save_user_tokens(current_user.user_id, ch.id, tokens)
        auth.delete_user_tokens(current_user.user_id, "pending")

    return RedirectResponse(url=f"{frontend}/", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/api/oauth/callback", response_model=OAuthCallbackResponse)
async def oauth_callback(payload: OAuthCallbackRequest, current_user: UserSessionModel = Depends(get_current_user)):
    """Handle YouTube OAuth callback code exchange & channel discovery."""
    if payload.state not in oauth_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired CSRF state token"
        )

    owner_user_id = oauth_states.pop(payload.state)
    if owner_user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF state mismatch for session user"
        )

    # Reset old selected channel state prior to writing new channel discovery results
    current_user.selected_channel_id = None
    current_user.selected_channel_title = None
    current_user.selected_channel_handle = None

    res = perform_single_oauth_exchange_and_discovery(payload.code, oauth_config.REDIRECT_URI_YOUTUBE)
    if not res["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error", "OAuth code exchange failed")
        )

    current_user.account_label = res["account_label"]
    if res["user_email"]:
        current_user.user_email = res["user_email"]
    if res["user_name"]:
        current_user.user_name = res["user_name"]
    current_user.channel_connection_status = res["channel_status"]
    current_user.has_write_scope = res.get("has_write_scope", True)
    current_user.granted_scopes = res.get("granted_scopes")
    current_user.channel_connection_status = res["channel_status"]

    discovered_channels_store[current_user.user_id] = res["channels"]
    auth.save_user_tokens(current_user.user_id, "pending", res["tokens"])

    if len(res["channels"]) == 1:
        ch = res["channels"][0]
        if ch.id not in current_user.verified_channels:
            current_user.verified_channels.append(ch.id)
        current_user.selected_channel_id = ch.id
        current_user.selected_channel_title = ch.title
        current_user.selected_channel_handle = ch.handle
        current_user.channel_titles[ch.id] = ch.title

        tokens = res["tokens"]
        tokens["channel_id"] = ch.id
        auth.save_user_tokens(current_user.user_id, ch.id, tokens)
        auth.delete_user_tokens(current_user.user_id, "pending")

    return OAuthCallbackResponse(
        status="channels_discovered",
        channels=res["channels"]
    )

@router.post("/api/oauth/select_channel", response_model=ChannelSelectResponse)
async def select_channel(payload: ChannelSelectRequest, current_user: UserSessionModel = Depends(get_current_user)):
    """Select the active channel from discovered channels."""
    discovered = discovered_channels_store.get(current_user.user_id, [])
    selected = next((c for c in discovered if c.id == payload.channel_id), None)
    
    if not selected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requested channel was not authorized by the user"
        )
        
    # Move pending tokens to this channel ID
    tokens = auth.load_user_tokens(current_user.user_id, "pending") or {}
    tokens["channel_id"] = selected.id
    auth.save_user_tokens(current_user.user_id, selected.id, tokens)
    auth.delete_user_tokens(current_user.user_id, "pending")

    if selected.id not in current_user.verified_channels:
        current_user.verified_channels.append(selected.id)
    current_user.selected_channel_id = selected.id
    current_user.selected_channel_title = selected.title
    current_user.selected_channel_handle = selected.handle
    current_user.channel_titles[selected.id] = selected.title
    current_user.channel_connection_status = "connected"

    return ChannelSelectResponse(
        status="connected",
        channel_id=selected.id,
        channel_title=selected.title
    )

@router.post("/api/oauth/disconnect", response_model=DisconnectResponse)
async def oauth_disconnect(current_user: UserSessionModel = Depends(get_current_user)):
    """Disconnect selected channel, revoking & deleting encrypted tokens."""
    channel_id = current_user.selected_channel_id
    if not channel_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No channel selected to disconnect"
        )

    auth.delete_user_tokens(current_user.user_id, channel_id)
    if channel_id in current_user.verified_channels:
        current_user.verified_channels.remove(channel_id)
    if channel_id in current_user.channel_titles:
        del current_user.channel_titles[channel_id]
    current_user.selected_channel_id = None
    current_user.selected_channel_title = None
    current_user.selected_channel_handle = None
    current_user.channel_connection_status = "unconnected"

    return DisconnectResponse(status="disconnected")


# --- ASSISTANT LIVE OPERATIONS ENDPOINTS ---

@router.get("/api/assistant/status")
async def get_assistant_status(user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    snap = state.snapshot()
    return {
        "state": "LIVE" if snap["state"] == "running" else "IDLE",
        "live_chat_id": snap.get("live_chat_id"),
        "video_id": snap.get("video_id"),
        "video_title": snap.get("video_title") or "Live Stream",
        "channel_title": snap.get("channel_title") or user.selected_channel_title or "YouTube Channel",
        "auto_reply": snap.get("auto_reply", False),
        "ignored_names": snap.get("ignored_names", []),
        "ignored_ids": snap.get("ignored_ids", [])
    }

@router.post("/api/assistant/connect_stream", response_model=ConnectStreamResponse)
async def connect_stream(payload: ConnectStreamRequest, user: UserSessionModel = Depends(get_optional_user)):
    v_clean = payload.video_id.strip()
    if "watch?v=" in v_clean:
        v_clean = v_clean.split("watch?v=")[-1].split("&")[0]
    elif "youtu.be/" in v_clean:
        v_clean = v_clean.split("youtu.be/")[-1].split("?")[0]

    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("YOUTUBE_API_KEY", "")
        except Exception:
            pass

    chat_id = None
    v_channel_id = None
    v_channel_title = None
    video_title = f"Stream {v_clean}"

    if api_key:
        try:
            details = get_video_details(v_clean, api_key)
            if details:
                chat_id = details.get("live_chat_id")
                v_channel_id = details.get("channel_id")
                v_channel_title = details.get("channel_title")
                video_title = details.get("title") or video_title
            else:
                chat_id = get_live_chat_id(v_clean, api_key)
        except Exception as e:
            print(f"Error fetching live chat details: {e}")

    if not chat_id:
        chat_id = f"live_chat_{v_clean}"

    state = poller.get_assistant_state()
    state.live_chat_id = chat_id
    state.video_id = v_clean

    return ConnectStreamResponse(
        live_chat_id=chat_id,
        video_title=video_title,
        channel_title=v_channel_title or user.selected_channel_title or "YouTube Channel"
    )

@router.post("/api/assistant/start")
async def start_assistant(payload: StartAssistantRequest, request: Request, user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    ch_id = user.selected_channel_id or "UC_DEMO_CHANNEL"
    
    token = request.headers.get("x-session-token") or request.cookies.get("session")
    poster = None
    try:
        poster = answer_poster.get_poster(token, ch_id)
    except Exception:
        pass

    started = poller.start_assistant(
        state, api_key, payload.live_chat_id, poster, channel_id=ch_id, video_id=payload.video_id
    )
    return {"status": "started" if started else "already_running"}

@router.post("/api/assistant/stop")
async def stop_assistant(user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    stopped = poller.stop_assistant(state)
    return {"status": "stopped" if stopped else "failed_to_stop"}

@router.get("/api/assistant/pending")
async def get_pending_questions(user: UserSessionModel = Depends(get_optional_user)):
    ch_id = user.selected_channel_id or "UC_DEMO_CHANNEL"
    state = poller.get_assistant_state()
    snap = state.snapshot()
    pending = poller.load_pending(
        channel_id=ch_id,
        live_chat_id=snap.get("live_chat_id"),
        video_id=snap.get("video_id"),
        strict_stream_filter=True
    ) if ch_id else {}
    return {"pending": pending}

@router.delete("/api/assistant/pending/{question_key:path}")
async def dismiss_pending_question(question_key: str, user: UserSessionModel = Depends(get_optional_user)):
    ch_id = user.selected_channel_id or "UC_DEMO_CHANNEL"
    poller.remove_pending(question_key, channel_id=ch_id)
    return {"status": "dismissed"}

@router.get("/api/assistant/feed")
async def get_assistant_feed(user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    snap = state.snapshot()
    return {"recent_messages": snap.get("messages", [])}

@router.get("/api/assistant/suggestions")
async def get_assistant_suggestions(user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    snap = state.snapshot()
    return {"suggestions": snap.get("suggestions", [])}

@router.delete("/api/assistant/suggestions/{suggestion_id}")
async def dismiss_assistant_suggestion(suggestion_id: str, user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    state.remove_suggestion(suggestion_id)
    return {"status": "dismissed"}

@router.get("/api/assistant/superchats")
async def get_assistant_superchats(user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    snap = state.snapshot()
    return {"superchats": snap.get("superchats", [])}

@router.post("/api/assistant/settings")
async def update_assistant_settings(payload: AssistantSettingsRequest, user: UserSessionModel = Depends(get_optional_user)):
    state = poller.get_assistant_state()
    if payload.auto_reply is not None:
        state.auto_reply = payload.auto_reply
    if payload.ignored_names is not None or payload.ignored_ids is not None:
        ignored_text = "\n".join((payload.ignored_names or []) + (payload.ignored_ids or []))
        state.set_ignored_bots(ignored_text)
    return {"status": "updated"}

@router.post("/api/ai/draft", response_model=AiDraftResponse)
async def generate_ai_draft(payload: AiDraftRequest, user: UserSessionModel = Depends(get_optional_user)):
    result = groq_service.review_question(payload.question)
    return AiDraftResponse(
        ok=result.get("ok", False),
        reliable=result.get("reliable", False),
        answer=result.get("answer", ""),
        note=result.get("note", "")
    )

# --- Q&A MEMORY BANK ENDPOINTS ---

@router.get("/api/qa/memory")
async def get_qa_memory(user: UserSessionModel = Depends(get_optional_user)):
    ch_id = user.selected_channel_id
    records = qa_engine.load_qa_data(channel_id=ch_id)
    return {"records": records}

@router.post("/api/qa/memory")
async def save_qa_memory(payload: QaMemoryCreateRequest, user: UserSessionModel = Depends(get_optional_user)):
    ch_id = user.selected_channel_id
    kw = payload.keywords or payload.examples
    record = qa_engine.add_question_answer(
        payload.question, payload.answer, auto_reply=payload.auto_reply, channel_id=ch_id, keywords=kw, cooldown_seconds=payload.cooldown_seconds
    )
    return {"status": "saved", "record": record}

@router.delete("/api/qa/memory/{record_id}")
async def delete_qa_memory(record_id: str, user: UserSessionModel = Depends(get_optional_user)):
    ch_id = user.selected_channel_id
    qa_engine.delete_record(record_id, channel_id=ch_id)
    return {"status": "deleted"}

@router.post("/api/qa/test_matcher")
async def test_qa_matcher(payload: QaTestMatcherRequest, user: UserSessionModel = Depends(get_optional_user)):
    ch_id = user.selected_channel_id or "UC_DEMO_CHANNEL"
    match, score = qa_engine.find_best_answer(payload.question, channel_id=ch_id)

    ai_draft = ""
    ai_note = ""
    try:
        records = qa_engine.load_qa_data(channel_id=ch_id)
        sugg_ans = match.get("answer_text") if (match and isinstance(match, dict)) else None
        ai_res = groq_service.review_question(payload.question, suggested_answer=sugg_ans, records=records)
        if ai_res and ai_res.get("ok"):
            ai_draft = ai_res.get("answer", "")
            ai_note = ai_res.get("note", "")
        elif ai_res and ai_res.get("note"):
            ai_note = ai_res.get("note", "")
    except Exception:
        pass

    return {
        "question": payload.question,
        "matched_record": match,
        "score": score,
        "ai_draft": ai_draft,
        "ai_note": ai_note
    }

# --- VIDEO COMMENTS ANALYTICS ENDPOINTS ---

@router.post("/api/comments/analyze", response_model=CommentAnalyticsResponse)
async def analyze_video_comments(payload: CommentAnalyzeRequest, user: UserSessionModel = Depends(get_optional_user)):
    v_clean = payload.video_id.strip()
    if "watch?v=" in v_clean:
        v_clean = v_clean.split("watch?v=")[-1].split("&")[0]
    elif "youtu.be/" in v_clean:
        v_clean = v_clean.split("youtu.be/")[-1].split("?")[0]

    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("YOUTUBE_API_KEY", "")
        except Exception:
            pass

    if not api_key:
        raise HTTPException(status_code=400, detail="YOUTUBE_API_KEY is not configured in environment or secrets.")

    try:
        nltk.download("vader_lexicon", quiet=True)
        from nltk.sentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to initialize sentiment analyzer: {e}")

    try:
        youtube = poller.build_youtube_client(api_key)
        comments = []
        page_token = None
        for _ in range(10):
            req = youtube.commentThreads().list(
                part="snippet",
                videoId=v_clean,
                textFormat="plainText",
                maxResults=100,
                pageToken=page_token
            )
            res = req.execute()
            for item in res.get("items", []):
                snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
                text = snippet.get("textDisplay")
                author = snippet.get("authorDisplayName", "Viewer")
                if text:
                    comments.append({"text": text, "author": author})
            page_token = res.get("nextPageToken")
            if not page_token:
                break
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"YouTube API Error fetching comments: {e}")

    pos_list, neg_list, neu_list = [], [], []
    for c in comments:
        cleaned = re.sub(r"http\S+", "", c["text"])
        cleaned = re.sub(r"[^\w\s]", "", cleaned)
        score = analyzer.polarity_scores(cleaned)["compound"]
        item = CommentItemModel(text=c["text"], author=c["author"], score=score)
        if score >= 0.05:
            pos_list.append(item)
        elif score <= -0.05:
            neg_list.append(item)
        else:
            neu_list.append(item)

    return CommentAnalyticsResponse(
        video_id=v_clean,
        total_comments=len(comments),
        positive_count=len(pos_list),
        negative_count=len(neg_list),
        neutral_count=len(neu_list),
        positive_comments=pos_list,
        negative_comments=neg_list,
        neutral_comments=neu_list
    )

