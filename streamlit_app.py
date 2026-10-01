"""Stream Assistant control panel (Streamlit).

Cinematic, High-Performance Control Panel for YouTube Live Streams.
"""

import os
import re

import nltk
import requests
import streamlit as st
from dotenv import load_dotenv
from googleapiclient.errors import HttpError
from nltk.sentiment import SentimentIntensityAnalyzer

import answer_poster
import groq_service
import live_chat_poller as poller
import qa_engine
from backend import storage
from livechat_id_generator import get_live_chat_id, get_video_details

load_dotenv()

st.set_page_config(
    page_title="Stream Assistant — YouTube Live Chat",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

nltk.download("vader_lexicon", quiet=True)

MAX_COMMENT_PAGES = 10


def get_backend_url():
    """Return configured backend URL from st.secrets, environment, or default localhost:8000."""
    try:
        if "BACKEND_URL" in st.secrets and st.secrets["BACKEND_URL"]:
            return st.secrets["BACKEND_URL"].rstrip("/")
    except Exception:
        pass
    return os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")


@st.cache_resource
def ensure_backend_running():
    """If backend URL points to localhost and is not responding, launch uvicorn in a background thread."""
    backend_url = get_backend_url()
    if "localhost" in backend_url or "127.0.0.1" in backend_url:
        try:
            res = requests.get(f"{backend_url}/health", timeout=1.0)
            if res.status_code == 200:
                return
        except Exception:
            pass

        import threading
        import time
        import uvicorn
        from backend.main import app as fastapi_app

        def run_uvicorn():
            uvicorn.run(fastapi_app, host="127.0.0.1", port=8000, log_level="warning")

        t = threading.Thread(target=run_uvicorn, daemon=True)
        t.start()

        for _ in range(15):
            try:
                res = requests.get(f"{backend_url}/health", timeout=0.5)
                if res.status_code == 200:
                    break
            except Exception:
                time.sleep(0.2)


def inject_cinematic_styles():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
        
        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        .stApp {
            background: radial-gradient(circle at 50% 0%, #151C28 0%, #0B0E14 100%);
            color: #F1F5F9;
        }

        /* Hero Banner Container */
        .hero-banner {
            background: linear-gradient(135deg, rgba(20, 26, 36, 0.85) 0%, rgba(11, 14, 20, 0.95) 100%);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            padding: 24px 28px;
            margin-bottom: 24px;
            box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .hero-title {
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(135deg, #00F2FE 0%, #4FACFE 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin: 0;
            letter-spacing: -0.5px;
        }

        .hero-subtitle {
            color: #94A3B8;
            font-size: 0.95rem;
            margin-top: 4px;
        }

        /* Glass Cards */
        .glass-card {
            background: rgba(20, 26, 36, 0.65);
            backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 14px;
            padding: 20px;
            margin-bottom: 16px;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }

        .glass-card:hover {
            border-color: rgba(0, 242, 254, 0.3);
        }

        /* Live Pulsing Dot */
        .live-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            background-color: #FF3B5C;
            border-radius: 50%;
            margin-right: 8px;
            box-shadow: 0 0 10px #FF3B5C;
            animation: pulse-live 1.5s infinite;
        }

        @keyframes pulse-live {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(255, 59, 92, 0.7); }
            70% { transform: scale(1.1); box-shadow: 0 0 0 8px rgba(255, 59, 92, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(255, 59, 92, 0); }
        }

        /* Metric Cards */
        [data-testid="stMetric"] {
            background: rgba(22, 29, 41, 0.7) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 12px !important;
            padding: 14px 18px !important;
            backdrop-filter: blur(10px) !important;
        }

        [data-testid="stMetricLabel"] {
            color: #94A3B8 !important;
            font-size: 0.85rem !important;
            font-weight: 500 !important;
        }

        [data-testid="stMetricValue"] {
            color: #F8FAFC !important;
            font-weight: 700 !important;
            font-size: 1.6rem !important;
        }

        /* Styled Buttons */
        .stButton button {
            border-radius: 10px !important;
            font-weight: 600 !important;
            transition: all 0.25s ease !important;
            border: 1px solid rgba(255, 255, 255, 0.12) !important;
        }

        .stButton button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        }

        /* Custom Tabs */
        .stTabs [data-baseweb="tab-list"] {
            gap: 12px;
            background: rgba(15, 21, 30, 0.6);
            padding: 8px 12px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.06);
        }

        .stTabs [data-baseweb="tab"] {
            border-radius: 8px;
            color: #94A3B8;
            padding: 10px 20px;
            font-weight: 600;
        }

        .stTabs [aria-selected="true"] {
            background: linear-gradient(135deg, rgba(0, 242, 254, 0.15) 0%, rgba(79, 172, 254, 0.15) 100%) !important;
            color: #00F2FE !important;
            border: 1px solid rgba(0, 242, 254, 0.3) !important;
        }

        /* Sidebar Styling */
        section[data-testid="stSidebar"] {
            background: #0D121B !important;
            border-right: 1px solid rgba(255, 255, 255, 0.06);
        }

        /* Badges */
        .badge-cyan {
            background: rgba(0, 242, 254, 0.12);
            color: #00F2FE;
            border: 1px solid rgba(0, 242, 254, 0.3);
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 600;
        }

        .badge-amber {
            background: rgba(255, 184, 0, 0.12);
            color: #FFB800;
            border: 1px solid rgba(255, 184, 0, 0.3);
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 600;
        }

        .badge-green {
            background: rgba(16, 185, 129, 0.12);
            color: #10B981;
            border: 1px solid rgba(16, 185, 129, 0.3);
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def get_sentiment_analyzer():
    return SentimentIntensityAnalyzer()


@st.cache_resource
def get_assistant_state():
    return poller.get_assistant_state()


@st.cache_resource
def _poster_holder():
    try:
        return {"poster": answer_poster.get_poster(st.session_state.get("session_token"), st.session_state.get("channel_id"))}
    except Exception:
        return {"poster": None}


def get_api_key():
    try:
        key = st.secrets["YOUTUBE_API_KEY"]
        if key:
            return key
    except (KeyError, FileNotFoundError):
        pass
    return os.environ.get("YOUTUBE_API_KEY", "")


# --- SIDEBAR CONTROL PANEL ---


def render_sidebar():
    state = get_assistant_state()
    holder = _poster_holder()
    api_key = get_api_key()

    st.sidebar.markdown("## 🎬 **Stream Assistant Pro**")
    
    if st.session_state.get("manual_mode"):
        st.sidebar.info("⚡ Local manual video mode (Unverified ownership)")
    elif st.session_state.get("account_label"):
        st.sidebar.info(f"👤 **{st.session_state['account_label']}**")
    elif st.session_state.get("session_token"):
        st.sidebar.info("👤 Google account connected")

    if st.session_state.get("session_token") or st.session_state.get("manual_mode"):
        if st.sidebar.button("🚪 Log out", key="sidebar_logout_btn", use_container_width=True):
            token = st.session_state.get("session_token")
            if token:
                try:
                    requests.post(f"{get_backend_url()}/api/auth/logout", headers={"x-session-token": token}, timeout=5)
                except Exception:
                    pass
            if holder["poster"]:
                holder["poster"].stop()
                holder["poster"] = None
            poller.stop_assistant(state)
            for k in ["session_token", "channel_id", "channel_title", "account_label", "user_id", "channel_connection_status", "manual_mode"]:
                st.session_state.pop(k, None)
            st.rerun()

    if not api_key:
        st.sidebar.warning(
            "⚠️ YOUTUBE_API_KEY missing. Add it to .streamlit/secrets.toml or .env"
        )

    st.sidebar.divider()

    # --- YouTube Channel Status ---
    if st.session_state.get("channel_id"):
        ch_title = st.session_state.get("channel_title")
        ch_id = st.session_state.get("channel_id")
        st.sidebar.markdown(f"<span class='badge-green'>Verified Channel</span>", unsafe_allow_html=True)
        if ch_title:
            st.sidebar.markdown(f"**{ch_title}**")
            st.sidebar.caption(f"`{ch_id}`")
        else:
            st.sidebar.markdown(f"**{ch_id}**")

        if st.sidebar.button("Disconnect Channel", key="oauth_disconnect_btn", use_container_width=True):
            requests.post(f"{get_backend_url()}/api/oauth/disconnect", headers={"x-session-token": st.session_state.get("session_token")})
            if holder["poster"]:
                holder["poster"].stop()
                holder["poster"] = None
            st.session_state.pop("channel_id", None)
            st.session_state.pop("channel_title", None)
            st.sidebar.info("Channel disconnected.")
            st.rerun()
    elif st.session_state.get("channel_connection_status") == "no_channels":
        st.sidebar.warning("No YouTube channel found for this account.")
    elif st.session_state.get("channel_connection_status") == "missing_scope":
        st.sidebar.warning("YouTube write permission missing. Please reconnect.")

    st.sidebar.divider()

    # Auto-reply toggle
    state.auto_reply = st.sidebar.checkbox(
        "🤖 Auto-reply on high confidence (≥ 0.80)",
        value=state.auto_reply,
        disabled=holder["poster"] is None,
        help="Automated replies trigger only when Q&A confidence match reaches 80% or higher.",
    )

    st.sidebar.divider()

    # Groq AI Status
    if groq_service.get_api_key():
        st.sidebar.markdown(f"<span class='badge-cyan'>Groq AI Ready ({groq_service.get_model()})</span>", unsafe_allow_html=True)
    else:
        st.sidebar.caption("Groq AI off — add GROQ_API_KEY to enable AI drafts.")

    st.sidebar.divider()

    # Ignored Bots
    state.set_ignored_bots(
        st.sidebar.text_area(
            "Ignored Chat Bots",
            key="ignored_bots_text",
            placeholder="Streamlabs\nNightbot\nUCxxxxxxxx…",
            height=85,
            help="One bot name or channel ID per line. Filtered from feed and questions.",
        )
    )

    st.sidebar.divider()

    # Connect Video Stream
    video_id = st.sidebar.text_input(
        "Livestream Video ID or URL",
        placeholder="e.g. umkwDoV6lPk",
    )

    if st.sidebar.button("📡 Connect Video Stream", disabled=not video_id.strip() or not api_key, use_container_width=True):
        if state.thread is not None and not poller.stop_assistant(state):
            st.sidebar.error("Could not stop previous assistant instance.")
        else:
            try:
                # Clean video ID from URL if full URL is pasted
                v_clean = video_id.strip()
                if "watch?v=" in v_clean:
                    v_clean = v_clean.split("watch?v=")[-1].split("&")[0]
                elif "youtu.be/" in v_clean:
                    v_clean = v_clean.split("youtu.be/")[-1].split("?")[0]

                details = get_video_details(v_clean, api_key)
                if details:
                    chat_id = details["live_chat_id"]
                    v_channel_id = details["channel_id"]
                    v_channel_title = details["channel_title"]
                else:
                    chat_id = get_live_chat_id(v_clean, api_key)
                    v_channel_id = None
                    v_channel_title = None
            except Exception as error:
                st.sidebar.error(f"YouTube API error: {error}")
                chat_id = None
                v_channel_id = None
                v_channel_title = None

            if chat_id:
                st.session_state["live_chat_id"] = chat_id
                st.session_state["stream_channel_id"] = v_channel_id
                if v_channel_id:
                    st.session_state["stream_channel_title"] = v_channel_title
                    st.sidebar.success(f"Connected: {v_channel_title}")
                else:
                    st.sidebar.success(f"Connected: {chat_id[:16]}...")
            else:
                st.sidebar.error("No active live chat found for this video. Make sure it is currently LIVE.")

    live_chat_id = st.session_state.get("live_chat_id", "")
    app_channel_id = st.session_state.get("channel_id")

    running = get_assistant_state().snapshot()["state"] == "running"
    
    if st.sidebar.button(
        "🛑 Stop Assistant" if running else "▶️ Start Assistant",
        disabled=not live_chat_id,
        type="primary" if not running else "secondary",
        use_container_width=True,
    ):
        if running:
            if not poller.stop_assistant(state):
                st.sidebar.error("Assistant did not stop in time — try again.")
        else:
            started = poller.start_assistant(
                state, api_key, live_chat_id, holder["poster"], channel_id=app_channel_id
            )
            if not started:
                st.sidebar.info("Assistant already running.")

    return state


# --- STATUS BAR & HEADER ---


def render_header(state):
    snap = state.snapshot()
    status = snap["state"]
    channel_id = st.session_state.get("channel_id", "Default")
    live_chat_id = snap.get("live_chat_id", "")

    st.markdown(
        """
        <div class="hero-banner">
            <div>
                <h1 class="hero-title">🎬 Stream Assistant AI</h1>
                <div class="hero-subtitle">Real-time YouTube Live Chat Q&A & Automated Stream Moderation</div>
            </div>
        """,
        unsafe_allow_html=True,
    )

    if status == "running":
        st.markdown(
            f"<div><span class='live-dot'></span><span class='badge-cyan'>LIVE STREAMING</span></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<div><span class='badge-amber'>STANDBY IDLE</span></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    # Metric Dashboard Summary
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Assistant Status", "LIVE 🟢" if status == "running" else "IDLE ⏸️")
    with m2:
        pending_data = poller.load_pending(channel_id=channel_id) if channel_id else {}
        st.metric("Pending Questions", len(pending_data))
    with m3:
        st.metric("Live Chat Feed", len(snap.get("messages", [])))
    with m4:
        st.metric("Superchats Received", len(snap.get("superchats", [])))


# --- LIVE ASSISTANT FRAGMENTS ---


@st.fragment(run_every=2)
def render_live_feed(state):
    snap = state.snapshot()
    messages = snap["messages"]

    st.markdown("### 💬 Live Chat Feed")

    window = messages[-poller.SENTIMENT_WINDOW:]
    share = poller.negative_share(window)
    if window and share >= poller.NEGATIVE_SHARE_ALERT:
        st.error(
            f"⚠️ Negative Sentiment Spike: {int(share * 100)}% of the last "
            f"{len(window)} messages are negative."
        )

    if not messages:
        st.caption("No live messages yet — connect a video stream and start the assistant.")
        return

    for message in reversed(messages[-35:]):
        compound = message["sentiment"]
        if compound >= 0.05:
            badge = "<span class='badge-green'>Positive</span>"
        elif compound <= poller.NEGATIVE_COMPOUND:
            badge = "<span class='badge-amber'>Negative</span>"
        else:
            badge = "<span class='badge-cyan'>Neutral</span>"

        st.markdown(
            f"**{message['author']}** {badge}: {message['text']} "
            f"<span style='color: #64748B; font-size: 0.8rem;'>({compound:+.2f})</span>",
            unsafe_allow_html=True,
        )


@st.fragment(run_every=2)
def render_suggestions(state):
    holder = _poster_holder()
    snap = state.snapshot()
    running = snap["state"] == "running"

    st.markdown("### 💡 Suggested Answers (Medium Match)")

    if not snap["suggestions"]:
        st.caption("No medium-confidence suggestions right now.")
        return

    for suggestion in snap["suggestions"]:
        with st.container(border=True):
            st.markdown(f"❓ **{suggestion['author']}:** {suggestion['question']}")
            st.markdown(f"💡 **Suggested Answer** ({suggestion['score']:.2f} score): {suggestion['answer']}")
            
            p_col, d_col, ai_col = st.columns([1, 1, 1])

            if p_col.button("Post Response", key=f"suggest_post_{suggestion['id']}", disabled=not running or holder["poster"] is None):
                removed = state.remove_suggestion(suggestion["id"])
                if removed is not None:
                    queued = holder["poster"].post_answer(
                        removed["answer"],
                        state.live_chat_id,
                        record_id=removed["record_id"],
                    )
                    if queued:
                        if removed["record_id"]:
                            qa_engine.mark_used(removed["record_id"], channel_id=st.session_state.get("channel_id"))
                        st.toast("Response posted to live chat!")
                    else:
                        st.warning("Post cooldown active.")

            if d_col.button("Dismiss", key=f"suggest_dismiss_{suggestion['id']}"):
                state.remove_suggestion(suggestion["id"])
                st.toast("Suggestion dismissed.")

            if ai_col.button("AI Check", key=f"suggest_ai_{suggestion['id']}", disabled=not groq_service.get_api_key()):
                result = groq_service.review_question(
                    suggestion["question"],
                    suggested_answer=suggestion["answer"],
                )
                if not result["ok"]:
                    st.warning(f"AI unavailable: {result['note']}")
                elif result["reliable"]:
                    st.info(f"AI Verified: {result['answer']}")
                else:
                    st.warning("AI could not confirm match from approved Q&A.")


@st.fragment(run_every=2)
def render_superchats(state):
    snap = state.snapshot()

    st.markdown("### 💰 Super Chats")

    if not snap["superchats"]:
        st.caption("No Super Chats received yet.")
        return

    for alert in snap["superchats"]:
        with st.container(border=True):
            text = f": {alert['text']}" if alert["text"] else ""
            st.markdown(f"💎 **{alert['author']}** — <span class='badge-amber'>{alert['amount']}</span>{text}", unsafe_allow_html=True)
            if st.button("Acknowledge", key=f"sc_ack_{alert['id']}"):
                state.acknowledge_superchat(alert["id"])
                st.toast("Super Chat acknowledged.")


@st.fragment(run_every=2)
def render_pending(state):
    holder = _poster_holder()
    running = state.snapshot()["state"] == "running"
    channel_id = st.session_state.get("channel_id")
    if not channel_id:
        st.warning("⚠️ No authorized application channel connected. Connect your YouTube channel to manage Q&A.")
        return

    st.markdown("### 🙋 New Questions from Chat")

    if not running:
        st.caption("Assistant is stopped. Connect a live stream and click 'Start Assistant' to see new questions from chat.")
        return

    pending = poller.load_pending(channel_id=channel_id)

    if not pending:
        st.caption("No new pending questions right now.")
        return

    for key, entry in sorted(pending.items(), key=lambda kv: -kv[1]["count"]):
        examples = entry.get("examples") or [key]
        occurrences = entry.get("occurrences", [])
        curr_status = entry.get("status", "pending")
        
        target_occ = occurrences[0] if occurrences else {}
        if len(occurrences) > 1:
            occ_labels = [f"Occurrence #{i+1}: {o.get('author_name', 'viewer')} ({o.get('timestamp', '')[:19]})" for i, o in enumerate(occurrences)]
            selected_idx = st.selectbox("Select Viewer Occurrence", range(len(occurrences)), format_func=lambda i: occ_labels[i], key=f"occ_select_{key}")
            target_occ = occurrences[selected_idx]

        occ_author = target_occ.get("author_name", "viewer")
        occ_chat_id = target_occ.get("live_chat_id") or state.live_chat_id

        with st.expander(f"❓ “{examples[0]}” — asked {entry['count']}× by {occ_author}", expanded=True):
            for example in examples:
                st.markdown(f"- {example}")

            if occ_chat_id:
                st.caption(f"Source: **{occ_author}** | Target Chat ID: `{occ_chat_id[:16]}...`")

            if curr_status == "outcome_unknown":
                st.warning("⚠️ Outcome Unknown: A previous post attempt timed out. Check YouTube live chat before retrying.")
            elif curr_status == "in_flight":
                st.info("⌛ Post in progress...")
            elif curr_status == "failed":
                err_detail = entry.get("error") or "Post rejected by YouTube API"
                st.error(f"⚠️ Post attempt failed: {err_detail}")
                if st.button("Clear error & retry", key=f"pending_retry_{key}"):
                    entry["status"] = "pending"
                    entry["error"] = None
                    pending_path = storage.get_pending_path(channel_id)
                    if pending_path:
                        qa_engine.atomic_write_json(pending_path, poller.load_pending(channel_id=channel_id))
                    st.rerun()

            # AI draft Fill
            if st.button(
                "✨ Get AI Draft",
                key=f"pending_ai_{key}",
                disabled=not groq_service.get_api_key(),
                help="Groq AI drafts a response from your approved Q&A.",
            ):
                result = groq_service.review_question(examples[0])
                if not result["ok"]:
                    st.warning(f"AI unavailable: {result['note']}")
                elif not result["reliable"]:
                    st.info("AI found no reliable answer in your approved Q&A — write your own response.")
                else:
                    st.session_state[f"pending_answer_{key}"] = result["answer"]
                    st.toast("AI draft loaded into answer box.")

            answer = st.text_area(
                "Your Answer Response", key=f"pending_answer_{key}", height=90, placeholder="Type exact answer to submit to YouTube Live Chat..."
            )
            auto = st.checkbox(
                "Allow auto-reply for this question in future",
                value=True,
                key=f"pending_auto_{key}",
            )

            save_col, post_col = st.columns(2)

            if save_col.button("💾 Save & Approve (Memory Only)", key=f"pending_save_{key}", use_container_width=True):
                if not answer.strip():
                    st.warning("Write an answer response first.")
                else:
                    record = qa_engine.add_question_answer(
                        examples[0], answer, auto_reply=auto, channel_id=channel_id
                    )
                    poller.remove_pending(key, channel_id=channel_id)
                    st.toast(f"Saved to Q&A memory ({record['id']}).")

            if post_col.button(
                "🚀 Save & Post Now",
                key=f"pending_post_{key}",
                type="primary",
                disabled=not st.session_state.get("session_token") or not channel_id or curr_status in ("in_flight", "outcome_unknown", "failed"),
                use_container_width=True,
            ):
                if not answer.strip():
                    st.warning("Write an answer response first.")
                else:
                    try:
                        res = requests.post(
                            f"{get_backend_url()}/api/channel/{channel_id}/post",
                            headers={"x-session-token": st.session_state.get("session_token")},
                            json={
                                "answer_text": answer,
                                "question_key": key,
                                "occurrence_id": target_occ.get("occurrence_id"),
                                "auto_reply_opt_in": auto
                            },
                            timeout=12
                        )
                        if res.status_code == 200:
                            data = res.json()
                            yt_id = data.get("youtube_message_id", "")
                            st.success(f"Posted to YouTube Live Chat! (ID: {yt_id})")
                            st.rerun()
                        elif res.status_code == 504:
                            st.warning("Network timeout contacting YouTube. Outcome is unknown. Check YouTube live chat before retrying.")
                        else:
                            try:
                                err_msg = res.json().get("detail", "Failed to post to live chat.")
                            except Exception:
                                err_msg = res.text or "Failed to post to live chat."
                            st.error(f"Cannot post: {err_msg}")
                            st.rerun()
                    except Exception as e:
                        st.error(f"Cannot post: {e}")


# --- VIDEO COMMENTS TAB ---


def create_youtube_client():
    api_key = get_api_key()
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY is missing in secrets or .env")
    return poller.build_youtube_client(api_key)


def fetch_video_comments(video_id):
    youtube = create_youtube_client()
    comments = []
    page_token = None

    for _ in range(MAX_COMMENT_PAGES):
        request = youtube.commentThreads().list(
            part="snippet",
            videoId=video_id.strip(),
            textFormat="plainText",
            maxResults=100,
            pageToken=page_token,
        )
        response = request.execute()
        for item in response.get("items", []):
            comment = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay")
            if comment:
                comments.append(comment)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return comments


def analyze_sentiment(text_list):
    analyzer = get_sentiment_analyzer()
    results = {"Positive": [], "Negative": [], "Neutral": []}

    for text in text_list:
        cleaned_text = re.sub(r"http\S+", "", text)
        cleaned_text = re.sub(r"[^\w\s]", "", cleaned_text)
        score = analyzer.polarity_scores(cleaned_text)["compound"]

        if score >= 0.05:
            category = "Positive"
        elif score <= -0.05:
            category = "Negative"
        else:
            category = "Neutral"

        results[category].append({"text": text, "score": score})

    return results


def show_sentiment_results(results):
    total = sum(len(items) for items in results.values())
    st.markdown(f"### 📊 Sentiment Analytics ({total} comments)")

    col1, col2, col3 = st.columns(3)
    col1.metric("🟢 Positive", len(results["Positive"]))
    col2.metric("🔴 Negative", len(results["Negative"]))
    col3.metric("⚪ Neutral", len(results["Neutral"]))

    for category, items in results.items():
        with st.expander(f"{category} Comments ({len(items)})"):
            if not items:
                st.write("No comments in this category.")
                continue
            for item in items:
                st.markdown(f"- {item['text']} `<span style='color:#64748B;'>score: {item['score']:.3f}</span>`", unsafe_allow_html=True)


def render_video_comments_tab():
    st.markdown("## 📊 Video Comments Sentiment Analysis")
    st.caption("Fetch and analyze public comment sentiment for any YouTube video.")

    video_id = st.text_input("YouTube Video ID", placeholder="e.g. I-XYQ-JwQ9Q", key="video_id_tab")

    if st.button("🔍 Analyze Video Comments", key="analyze_video", type="primary"):
        if not video_id.strip():
            st.warning("Enter a video ID first.")
            return

        try:
            with st.spinner("Fetching comments from YouTube API..."):
                comments = fetch_video_comments(video_id)

            if not comments:
                st.info("No public comments found.")
            else:
                show_sentiment_results(analyze_sentiment(comments))

        except HttpError as error:
            st.error(f"YouTube API Error: {error}")
        except Exception as error:
            st.error(str(error))


# --- QA MEMORY EDITOR TAB ---


def render_memory_editor():
    channel_id = st.session_state.get("channel_id")
    records = qa_engine.load_qa_data(channel_id=channel_id)

    st.markdown("## 🧠 Q&A Memory Bank")
    if channel_id:
        st.caption(f"Approved answers stored for channel **{channel_id}** at `data/channels/{channel_id}/qa_data.json`")
    else:
        st.caption("Approved answers stored in temporary memory session.")

    if channel_id:
        if st.button("📥 Import Legacy Q&A Data", key="legacy_qa_import"):
            count = qa_engine.import_legacy_qa(channel_id=channel_id)
            if count > 0:
                st.success(f"Imported {count} legacy Q&A records.")
                st.rerun()
            else:
                st.info("No new legacy Q&A records to import.")

    with st.container(border=True):
        st.markdown("#### ➕ Add New Q&A Pair")
        question = st.text_input("Question Example", placeholder="e.g. What camera do you use?")
        answer = st.text_area("Answer Response", placeholder="e.g. Sony ZV-E10 with kit lens.")
        auto_reply = st.checkbox("Allow Auto-reply for this question", value=True)

        if st.button("💾 Save to Memory Bank", key="memory_save", type="primary"):
            try:
                record = qa_engine.add_question_answer(question, answer, auto_reply=auto_reply, channel_id=channel_id)
                st.success(f"Saved to Q&A memory! (ID: {record['id']})")
                st.rerun()
            except ValueError as error:
                st.warning(str(error))

    st.divider()

    st.markdown("### 📚 Stored Q&A Records")
    if not records:
        st.info("Memory is empty. Anything added here will immediately match incoming questions.")
    else:
        for record in records:
            examples = record["original_question_examples"] or [record["normalized_question"]]
            auto_label = "<span class='badge-green'>Auto-reply ON</span>" if record["auto_reply"] else "<span class='badge-amber'>Manual</span>"
            with st.expander(f"❓ {examples[0]} — used {record['usage_count']}×"):
                st.markdown(f"**Answer:** {record['answer_text']}")
                st.markdown(f"Status: {auto_label} | ID: `{record['id']}` | Updated: `{record['updated_at'][:19]}`", unsafe_allow_html=True)
                for example in examples[1:]:
                    st.caption(f"Also phrased as: {example}")

                if st.button("🗑️ Delete Record", key=f"memory_delete_{record['id']}"):
                    qa_engine.delete_record(record["id"], channel_id=channel_id)
                    st.rerun()

    st.divider()
    st.markdown("### 🧪 Matcher Sandbox")
    tester = st.text_input("Try a viewer question phrase", placeholder="e.g. what camera u using?")
    if st.button("Test Matcher Confidence", key="memory_test"):
        match, score = qa_engine.find_best_answer(tester, channel_id=channel_id)
        if match is None or score < poller.SUGGEST_SCORE:
            st.info(f"No good match (best score {score:.2f}). Would route to Pending Queue.")
        else:
            band = "Auto-reply Eligible (≥ 0.80)" if score >= poller.AUTO_REPLY_SCORE else "Suggestion Band (0.50 - 0.79)"
            st.success(f"Matched! Score: **{score:.2f}** ({band})\n\n**Answer:** {match['answer_text']}")


# --- LOGIN & AUTHENTICATION FLOWS ---


def check_auth_token():
    if "code" in st.query_params and "state" in st.query_params:
        code = st.query_params["code"]
        state = st.query_params["state"]
        st.query_params.clear()

        backend_url = get_backend_url()
        if state.startswith("state_login_"):
            try:
                res = requests.post(
                    f"{backend_url}/api/auth/login/callback",
                    json={"code": code, "state": state},
                    timeout=10,
                )
                if res.status_code == 200:
                    data = res.json()
                    if "session_token" in data:
                        st.session_state["session_token"] = data["session_token"]
            except Exception as e:
                st.error(f"Login callback error: {e}")
        elif state.startswith("state_yt_"):
            token = st.session_state.get("session_token")
            if token:
                try:
                    requests.post(
                        f"{backend_url}/api/oauth/callback",
                        headers={"x-session-token": token},
                        json={"code": code, "state": state},
                        timeout=10,
                    )
                except Exception as e:
                    st.error(f"OAuth callback error: {e}")

    try:
        cookie_token = st.context.cookies.get("session")
        if cookie_token:
            st.session_state["session_token"] = cookie_token
    except Exception:
        pass


def fetch_me():
    token = st.session_state.get("session_token")
    headers = {}
    cookies = {}
    if token:
        headers["x-session-token"] = token
        cookies["session"] = token
    else:
        try:
            c = st.context.cookies.get("session")
            if c:
                headers["x-session-token"] = c
                cookies["session"] = c
        except Exception:
            pass
    
    if not headers and not cookies:
        return None

    try:
        res = requests.get(f"{get_backend_url()}/api/me", headers=headers, cookies=cookies)
        if res.status_code == 200:
            data = res.json()
            if "session_token" in cookies:
                st.session_state["session_token"] = cookies["session"]
            return data
        elif res.status_code == 401:
            st.session_state.pop("session_token", None)
    except Exception:
        pass
    return None


def login_page():
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown(
            """
            <div class="glass-card" style="text-align: center; padding: 36px 28px; margin-top: 40px;">
                <h1 class="hero-title" style="font-size: 2.4rem;">🎬 Stream Assistant AI</h1>
                <p class="hero-subtitle" style="font-size: 1rem; margin-bottom: 24px;">
                    Real-time YouTube Live Chat Q&A & Automated Moderation Platform
                </p>
                <div style="display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-bottom: 28px;">
                    <span class="badge-cyan">⚡ AI Drafts</span>
                    <span class="badge-green">🔴 Live Chat Posting</span>
                    <span class="badge-amber">🧠 Q&A Memory Engine</span>
                </div>
            """,
            unsafe_allow_html=True,
        )
        try:
            res = requests.get(f"{get_backend_url()}/api/auth/login/init")
            if res.status_code == 200:
                auth_url = res.json()["auth_url"]
                st.markdown(
                    f'<a href="{auth_url}" target="_self" style="text-decoration: none;">'
                    f'<button style="width: 100%; padding: 14px; font-size: 1rem; font-weight: 700; '
                    f'background: linear-gradient(135deg, #00F2FE 0%, #4FACFE 100%); color: #000; '
                    f'border: none; border-radius: 10px; cursor: pointer; box-shadow: 0 4px 20px rgba(0, 242, 254, 0.4);">'
                    f'🔐 Continue with Google Account</button></a>',
                    unsafe_allow_html=True,
                )
            elif res.status_code == 503:
                st.warning("Google OAuth login not configured. Please set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env")
            else:
                st.error("Backend login init failed.")
        except Exception as e:
            st.error(f"Cannot connect to backend: {e}")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚡ Continue in Manual Local Video Mode", key="login_manual_fallback", use_container_width=True):
            st.session_state["manual_mode"] = True
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


def channel_selection_page(me_data):
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown(
            """
            <div class="glass-card" style="padding: 32px 28px; margin-top: 40px;">
                <h2 style="margin: 0; color: #00F2FE;">Connect YouTube Channel</h2>
                <p style="color: #94A3B8; font-size: 0.9rem;">Authorize YouTube Live Chat posting permissions.</p>
            """,
            unsafe_allow_html=True,
        )
        acc_label = me_data.get('account_label') or "Google account connected"
        st.info(f"Logged in as **{acc_label}**")

        token = st.session_state.get("session_token")
        if st.button("🔗 Connect YouTube Channel", type="primary", use_container_width=True):
            res = requests.get(f"{get_backend_url()}/api/oauth/init", headers={"x-session-token": token})
            if res.status_code == 200:
                st.markdown(f'<meta http-equiv="refresh" content="0;url={res.json()["auth_url"]}">', unsafe_allow_html=True)
            else:
                st.error("Failed to initialize OAuth")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⚡ Continue in Manual Local Video Mode", use_container_width=True):
            st.session_state["manual_mode"] = True
            st.rerun()

        if st.button("🚪 Log out", use_container_width=True):
            requests.post(f"{get_backend_url()}/api/auth/logout", headers={"x-session-token": token})
            st.session_state.pop("session_token", None)
            st.session_state.pop("channel_id", None)
            st.session_state.pop("manual_mode", None)
            st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


# --- MAIN ENTRYPOINT ---


def main():
    inject_cinematic_styles()
    ensure_backend_running()
    check_auth_token()
    me_data = fetch_me()

    if not me_data and not st.session_state.get("manual_mode"):
        login_page()
        return

    if me_data:
        st.session_state["user_id"] = me_data.get("user_id", "")
        st.session_state["account_label"] = me_data.get("account_label", "Google account connected")
        st.session_state["channel_connection_status"] = me_data.get("channel_connection_status", "unconnected")

        if not st.session_state.get("channel_id") and not st.session_state.get("manual_mode"):
            verified = me_data.get("verified_channels", [])
            if verified and me_data.get("selected_channel_id"):
                st.session_state["channel_id"] = me_data["selected_channel_id"]
                ch_title = me_data.get("selected_channel_title") or (
                    me_data.get("channel_titles", {}).get(me_data["selected_channel_id"])
                )
                if ch_title:
                    st.session_state["channel_title"] = ch_title
                if _poster_holder()["poster"] is None:
                    _poster_holder()["poster"] = answer_poster.get_poster(st.session_state["session_token"], st.session_state["channel_id"])
                st.rerun()
            else:
                channel_selection_page(me_data)
                return

    state = render_sidebar()
    render_header(state)

    assistant_tab, comments_tab, memory_tab = st.tabs(
        ["💬 Live Operations", "📊 Comments Analytics", "🧠 Q&A Memory Bank"]
    )

    with assistant_tab:
        col_left, col_right = st.columns([7, 5])
        with col_left:
            render_pending(state)
        with col_right:
            render_superchats(state)
            st.divider()
            render_suggestions(state)
            st.divider()
            render_live_feed(state)

    with comments_tab:
        render_video_comments_tab()

    with memory_tab:
        render_memory_editor()


if __name__ == "__main__":
    main()
