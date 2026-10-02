# Project Analysis: Comment Analyzer / Stream Assistant AI

**Last analyzed:** 2026-10-02  
**Repository:** `D:\work\Comment-analyzer`

---

## Project Summary

### Purpose
**Stream Assistant AI** is a real-time YouTube Live Chat Q&A automation and moderation platform designed for live stream hosts and content creators.

### Main User Problem Solved
During live broadcasts, streamers face high volumes of incoming chat messages. Reading, filtering, deduplicating, and answering recurring viewer questions in real time is mentally taxing and disrupts stream flow. Stream Assistant AI automates this process by:
1. Polling YouTube Live Chat in real time.
2. Detecting viewer questions and scoring sentiment (VADER).
3. Matching questions against an approved Q&A Memory Bank (lexical Jaccard matching + optional Groq AI drafting).
4. Auto-replying to high-confidence matches (if enabled) or queuing medium-confidence suggestions and unrecognized questions for host review.
5. Allowing one-click posting of approved responses back to YouTube Live Chat using authorized channel OAuth tokens.

### Main Technologies Used
* **Frontend UI**: Streamlit 1.64+ (with custom cinematic dark theme and fragment-based 2-second auto-refreshing UI components).
* **Backend API**: FastAPI 0.142+, Uvicorn server, Pydantic v2 data models.
* **Security & Auth**: Cryptography (`Fernet` AES encryption for stored OAuth tokens), `google-auth-oauthlib`, OpenID Connect.
* **Integrations**: `google-api-python-client` (YouTube Data API v3), NLTK (`SentimentIntensityAnalyzer` VADER), Groq API (OpenAI-compatible chat completions).
* **Language & Environment**: Python 3.14+, `python-dotenv`, `uv`.

### Application Architecture Classification
* **Mixed Setup (Local + Cloud-Deployable)**:
  * **Local Execution**: Streamlit UI runs on port `8501`, FastAPI backend runs on port `8000`.
  * **Streamlit Cloud Deployment**: Streamlit UI runs on port `8501`; `streamlit_app.py` automatically spawns FastAPI/Uvicorn on `127.0.0.1:8000` in a background daemon thread inside the same container. Streamlit UI communicates with internal FastAPI endpoints via localhost HTTP calls.

---

## Repository Structure

```
Comment-analyzer/
├── backend/                        # FastAPI Backend Service
│   ├── __init__.py
│   ├── auth.py                     # Token Fernet encryption & user directory storage
│   ├── deps.py                     # Session validation & dependency injection
│   ├── main.py                     # FastAPI application setup & CORS configuration
│   ├── models.py                   # Pydantic request/response schemas
│   ├── oauth_config.py             # Google Client ID/Secret & OAuth URI configuration
│   ├── routes.py                   # Authentication, OAuth callback & post API endpoints
│   └── storage.py                  # Inter-process file locking & path utilities
├── data/                           # Runtime Storage Directory (Gitignored)
│   ├── channels/                   # Channel-scoped Q&A, pending queues, logs, cooldowns
│   ├── logs/                       # System & post audit logs
│   └── users/                      # User-scoped encrypted Fernet OAuth token files
├── answer_poster.py                # Single-writer queue worker for posting to YouTube
├── groq_service.py                 # Optional Groq LLM integration for AI question verification & drafting
├── live_chat_poller.py             # Poller thread, VADER sentiment, question routing & AssistantState
├── livechat_id_generator.py        # YouTube API helpers for activeLiveChatId & video details resolution
├── qa_engine.py                    # Q&A memory engine, lexical matcher (Jaccard), atomic JSON writer
├── streamlit_app.py                # Main Streamlit control panel UI entrypoint
├── requirements.txt                # Python dependencies list
├── README.md                       # Project documentation overview
└── tests/                          # Automated Test Suite
    ├── test_cookie_handoff.py
    ├── test_groq_service.py
    ├── test_m1_channel.py          # Multi-channel storage isolation tests
    ├── test_m2_backend.py          # FastAPI endpoint integration tests
    ├── test_m3_oauth.py            # OAuth callback & identity tests
    ├── test_poller.py              # Poller thread, IdRing & bot filter tests
    ├── test_poster_authoritative.py# Poster cooldown & lock tests
    └── test_stream_data_isolation.py # Stream-level data isolation regression tests
```

---

## Current Features Analysis

### 1. Streamlit Control Panel UI
* **Purpose**: Provides a real-time control panel for stream hosts to monitor live chat feed, negative sentiment alerts, Superchats, Q&A suggestions, pending questions, and Q&A memory bank.
* **Main Files**: [streamlit_app.py](file:///D:/work/Comment-analyzer/streamlit_app.py)
* **Input**: User clicks, text inputs, live stream URL/video ID.
* **Processing**: Renders glassmorphic UI, pulls snapshots from `live_chat_poller.AssistantState`, auto-refreshes fragments every 2 seconds.
* **Output**: Interactive metrics, live chat feed, pending question cards, response buttons.
* **Status**: **Implemented** (Verified in codebase & test suite).

### 2. Google OAuth Login
* **Purpose**: Authenticates stream hosts via Google OpenID Connect.
* **Main Files**: [backend/routes.py](file:///D:/work/Comment-analyzer/backend/routes.py), [backend/auth.py](file:///D:/work/Comment-analyzer/backend/auth.py), [backend/oauth_config.py](file:///D:/work/Comment-analyzer/backend/oauth_config.py)
* **Input**: User authorization code from Google OAuth redirect.
* **Processing**: Single authorization code exchange with `https://oauth2.googleapis.com/token`, identity token parsing, session generation (`session_token`), encrypted token storage.
* **Output**: `session_token` cookie and header, user identity (`user_id`, `account_label`, `user_email`).
* **Status**: **Implemented** (Verified by `test_m3_oauth.py`).

### 3. YouTube Channel Discovery & Connection
* **Purpose**: Discovers YouTube channels managed by the authenticated Google account and acquires write scope (`youtube.force-ssl`).
* **Main Files**: [backend/routes.py](file:///D:/work/Comment-analyzer/backend/routes.py), [backend/auth.py](file:///D:/work/Comment-analyzer/backend/auth.py)
* **Input**: OAuth access token with `https://www.googleapis.com/auth/youtube.force-ssl` scope.
* **Processing**: Calls YouTube API `channels.list(mine=True)`, checks write scope, prompts channel selection if multiple channels exist.
* **Output**: Selected verified channel ID (`selected_channel_id`), encrypted token file saved to `data/users/{user_id}/channels/{channel_id}/token.enc`.
* **Status**: **Implemented** (Verified by `test_m1_channel.py` & `test_m3_oauth.py`).

### 4. Live Stream / Video Selection
* **Purpose**: Resolves active `liveChatId` and video metadata from a YouTube video ID or URL.
* **Main Files**: [livechat_id_generator.py](file:///D:/work/Comment-analyzer/livechat_id_generator.py), [streamlit_app.py](file:///D:/work/Comment-analyzer/streamlit_app.py)
* **Input**: YouTube Video ID or full watch URL.
* **Processing**: Calls `youtube.videos().list(part="snippet,liveStreamingDetails", id=video_id)`.
* **Output**: `activeLiveChatId`, `channel_id`, `channel_title`, `video_title`.
* **Status**: **Implemented** (Verified by unit tests & live chat generator helpers).

### 5. YouTube Live-Chat Polling
* **Purpose**: Continuously fetches live chat messages from YouTube without overloading API quotas.
* **Main Files**: [live_chat_poller.py](file:///D:/work/Comment-analyzer/live_chat_poller.py)
* **Input**: `activeLiveChatId`, API key.
* **Processing**: Background thread polling loop obeying `pollingIntervalMillis` (min 5.0s floor), message deduplication via `IdRing`, bot filtering (ignored names/IDs), VADER sentiment scoring.
* **Output**: Updates `recent_messages`, `superchats`, negative sentiment ratio alerts.
* **Status**: **Implemented** (Verified by `test_poller.py`).

### 6. Question Detection & Confidence Band Routing
* **Purpose**: Detects viewer questions in live chat and routes them based on matching confidence against approved Q&A memory.
* **Main Files**: [live_chat_poller.py](file:///D:/work/Comment-analyzer/live_chat_poller.py), [qa_engine.py](file:///D:/work/Comment-analyzer/qa_engine.py)
* **Input**: Raw text message, author details.
* **Processing**: Question heuristic (`is_question`), token normalization, stop-word removal, Jaccard lexical match score calculation (`calculate_score`).
* **Routing Logic**:
  * **Score $\ge$ 0.80 & Auto-Reply ON**: Automatically queues answer for posting via `AnswerPoster`.
  * **0.50 $\le$ Score < 0.79**: Adds to `suggestions` array for manual UI review ("Post Response" / "Dismiss").
  * **Score < 0.50**: Adds to `pending` questions queue (`upsert_pending`) for host answering.
* **Status**: **Implemented** (Verified by `test_poller.py`).

### 7. AI Draft Generation (Groq Integration)
* **Purpose**: Generates grounded draft answers for pending viewer questions using host-approved Q&A memory.
* **Main Files**: [groq_service.py](file:///D:/work/Comment-analyzer/groq_service.py), [streamlit_app.py](file:///D:/work/Comment-analyzer/streamlit_app.py)
* **Input**: Viewer question string, approved Q&A records.
* **Processing**: Calls Groq API (`https://api.groq.com/openai/v1/chat/completions`) using model `openai/gpt-oss-120b` with strict system instructions prohibiting ungrounded claims.
* **Output**: Grounded answer string ($\le 200$ chars) or `NO_ANSWER`. Display-only; requires explicit host action to save or post.
* **Status**: **Implemented (Display-Only)** (Verified by `test_groq_service.py`).

### 8. Q&A Memory Bank
* **Purpose**: Stores host-approved question-answer pairs per channel for automated matching.
* **Main Files**: [qa_engine.py](file:///D:/work/Comment-analyzer/qa_engine.py), [backend/storage.py](file:///D:/work/Comment-analyzer/backend/storage.py)
* **Input**: Question text, answer text, auto-reply toggle, status (`approved` / `draft`).
* **Processing**: Thread-safe atomic JSON read/write to `data/channels/{channel_id}/qa_data.json`.
* **Output**: Structured Q&A memory records with usage counters and timestamps.
* **Status**: **Implemented** (Verified by `test_poller.py` & `test_m1_channel.py`).

### 9. Save & Approve vs Save & Post Now
* **Save & Approve (Memory Only)**: Saves Q&A pair to channel memory bank without posting to active live chat. Removes question from pending queue.
* **Save & Post Now**: Saves Q&A pair to memory bank AND calls backend endpoint `/api/channel/{channel_id}/post` to post the response to YouTube Live Chat immediately.
* **Main Files**: [streamlit_app.py](file:///D:/work/Comment-analyzer/streamlit_app.py), [backend/routes.py](file:///D:/work/Comment-analyzer/backend/routes.py)
* **Status**: **Implemented** (Verified by `test_m2_backend.py` & `test_poster_authoritative.py`).

### 10. Stream Session Data Isolation
* **Purpose**: Prevents old questions from previous live streams from appearing in the active stream queue.
* **Main Files**: [live_chat_poller.py](file:///D:/work/Comment-analyzer/live_chat_poller.py), [streamlit_app.py](file:///D:/work/Comment-analyzer/streamlit_app.py), [backend/routes.py](file:///D:/work/Comment-analyzer/backend/routes.py)
* **Processing**: `AssistantState` session generation ID counter, strict filtering in `load_pending(strict_stream_filter=True)` matching active `live_chat_id` and `video_id`, backend validation rejecting posts targeting mismatched liveChatIds.
* **Status**: **Implemented** (Verified by `test_stream_data_isolation.py`).

---

## End-to-End Data Flow

```
[ YouTube Live Chat ]
         │
         ▼ (YouTube API v3 liveChatMessages.list)
[ live_chat_poller.py ]
         │
         ├── Dedup (IdRing) & Bot Filter
         ├── Sentiment Analysis (VADER)
         └── Question Detection (is_question)
                 │
                 ├── Score >= 0.80 & Auto-Reply ON ──► [ answer_poster.py ] ──► YouTube Live Chat
                 ├── 0.50 <= Score < 0.79 ───────────► [ suggestions Array ] ──► Streamlit UI
                 └── Score < 0.50 ────────────────────► [ pending_questions.json ]
                                                               │
                                                               ▼
                                                      [ Streamlit UI ]
                                                               │
                                                  Host clicks "Save & Post Now"
                                                               │
                                                               ▼
                                                  [ FastAPI Backend /post ]
                                                               │
                                                 (Validates Chat ID & Token)
                                                               │
                                                               ▼
                                                 [ YouTube API Messages.insert ]
```

### Key Event Lifecycle Flows

1. **User Login**:
   - Host clicks "Continue with Google Account" in Streamlit UI.
   - Streamlit queries `/api/auth/login/init`, receives Google OAuth authorization URL.
   - User authenticates on Google; Google redirects back to redirect URI with `code` and `state`.
   - FastAPI `/api/auth/login/callback` exchanges `code` for tokens, creates `session_token`, stores user profile in memory session store, and redirects to Streamlit UI.

2. **Starting Assistant**:
   - Host enters video ID and clicks "Connect Video Stream" (resolving `activeLiveChatId`).
   - Host clicks "Start Assistant".
   - `poller.start_assistant()` clears old in-memory session, increments `generation` counter, sets `live_chat_id`, `video_id`, and spawns the background polling thread.

3. **New Chat Question Arrival**:
   - Poller thread fetches new chat batch.
   - Message is checked for question indicators (`is_question`).
   - If unrecognized ($\text{score} < 0.50$), `upsert_pending()` saves occurrence metadata (`occurrence_id`, `message_id`, `live_chat_id`, `video_id`, `author_name`, `timestamp`) into `pending_questions.json`.
   - Streamlit UI auto-refreshes (fragment `run_every=2`) and renders the new question card.

4. **Pressing Save & Approve**:
   - Question & answer are saved to `data/channels/{channel_id}/qa_data.json` via `qa_engine.add_question_answer()`.
   - Question entry is removed from pending queue via `poller.remove_pending()`.
   - No post request is sent to YouTube.

5. **Pressing Save & Post Now**:
   - UI sends POST request to `/api/channel/{channel_id}/post` with `session_token`, `question_key`, `answer_text`, and `occurrence_id`.
   - Backend validates user session token and verifies that `occurrence_id`'s `live_chat_id` matches active stream `live_chat_id`.
   - Backend loads decrypted OAuth access token from `data/users/{user_id}/channels/{channel_id}/token.enc` (refreshing token via Google OAuth endpoint if expired).
   - Backend issues HTTP POST to YouTube API `liveChatMessages.insert`.
   - On success (HTTP 200/201), backend logs message to `posted_messages.json`, updates pending entry status to `posted`, and returns `youtube_message_id`.

6. **Stopping Assistant**:
   - Host clicks "Stop Assistant".
   - `poller.stop_assistant()` sets `stop_event`, joins poller thread, clears `AnswerPoster` queue, resets in-memory session memory, and increments generation counter.
   - Streamlit UI pending view switches to idle status and displays empty active queue.

7. **Switching Streams**:
   - Host connects new video ID.
   - `poller.stop_assistant()` winds down old poller thread.
   - `poller.start_assistant()` initializes fresh stream state with new `live_chat_id` and `video_id`.
   - `load_pending(strict_stream_filter=True)` filters out previous stream questions, showing only questions from the new stream.

---

## Security and Privacy Review

### 1. Secret & Credentials Management
* **Source of Secrets**: Environment variables (`.env`) or Streamlit secrets (`.streamlit/secrets.toml`).
* **Protected Secrets**: `GOOGLE_CLIENT_SECRET`, `YOUTUBE_API_KEY`, `GROQ_API_KEY`, `ENCRYPTION_KEY`.
* **Finding**: No real secret values are hardcoded in source code files. `.env` and `.streamlit/secrets.toml` are gitignored.

### 2. OAuth Scopes
Requested minimum scopes:
* `openid`: OpenID Connect user authentication.
* `email`: Access to host's email address for account identification.
* `profile`: Access to host's basic profile details.
* `https://www.googleapis.com/auth/youtube.force-ssl`: Mandatory write permission required to post responses to YouTube Live Chat on behalf of the channel owner.

### 3. Token Encryption & Storage
* OAuth refresh and access tokens are encrypted using **Fernet (AES-128-CBC)** derived via SHA-256 from `ENCRYPTION_KEY`.
* Encrypted files are stored on disk at `data/users/{clean_user_id}/channels/{clean_channel_id}/token.enc` with strict directory creation permissions (`0o700`).

### 4. Data & Channel Isolation
* Data is strictly partitioned by `channel_id` under `data/channels/{channel_id}/`.
* Each streamer's Q&A memory bank, pending questions, cooldowns, and post logs are isolated in their respective channel folder.

---

## Current Limitations and Risks

1. **Unverified Live Production Posting**: While mock unit tests (`test_m2_backend.py`, `test_poster_authoritative.py`) verify API endpoints, actual YouTube live chat posting depends on Google OAuth consent screen status and YouTube channel live chat moderator permissions.
2. **YouTube Quota Limits**: YouTube Data API v3 enforces a daily quota limit (typically 10,000 units/day for default projects). `liveChatMessages.list` costs 5 units per call. Continuous polling at 5-second intervals consumes ~3,600 units/hour per active stream.
3. **Single-Process Poster Architecture**: `AnswerPoster` uses threading locks (`_active_posters_lock`) to enforce single-writer posting per channel within a single Python process. In multi-worker web server deployments (e.g. multi-process Gunicorn/Uvicorn), process-level locking would require Redis or inter-process locks.
4. **Lexical Jaccard Matcher Limitations**: `qa_engine.py` uses word token set overlap (Jaccard similarity). Syntactically different but semantically identical questions (e.g. "What camera do you use?" vs "Which camera is that?") match well, but structural rephrasings without common keywords may score below $0.50$ and route to the pending queue.

---

## Recommended Next Steps

### 1. Critical Priority
* **Google Cloud Console OAuth Verification**: Add tester emails under **OAuth consent screen > Test users** or submit the app for verification to avoid Google `403` access denied errors in production.
* **Production HTTPS Redirect URIs**: Ensure `REDIRECT_URI_LOGIN` and `REDIRECT_URI_YOUTUBE` in production deployment secrets match the public domain HTTPS callback URLs registered in Google Cloud Console.

### 2. High Priority
* **Quota Management & Adaptive Polling**: Dynamically adjust `MIN_POLL_SECONDS` based on stream chat velocity to conserve YouTube API quota during slow stream periods.
* **Semantic Vector Matcher Option**: Upgrade or supplement `qa_engine.py` Jaccard lexical matcher with lightweight semantic embeddings (e.g. Sentence-Transformers or OpenAI/Groq embeddings) for improved intent matching.

### 3. Medium Priority
* **Multi-Process Lock Provider**: Upgrade `AnswerPoster` single-writer locks to use file-based inter-process locks (`storage.interprocess_file_lock`) or Redis if scaling to multiple backend worker processes.
* **Webhooks / EventSub Support**: Explore YouTube WebSockets or push notifications (if supported in future YouTube API revisions) to replace HTTP polling.

### 4. Nice to Have
* **Custom UI Theme Switcher**: Provide high-contrast light and dark mode toggles for different streamer broadcasting software (OBS/Streamlabs browser docks).
* **Analytics Export**: CSV/JSON export option for session chat sentiment analytics and Superchat summaries.
