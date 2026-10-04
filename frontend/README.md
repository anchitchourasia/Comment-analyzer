# Stream Assistant AI - Angular Frontend

This project is the Angular 18+ frontend application for Stream Assistant AI, replacing the legacy Streamlit interface with a component-driven cinematic SPA architecture.

---

## Quick Start (Local Development)

### 1. Prerequisites
- Node.js (v18+ or v20+)
- npm (v9+)
- Python 3.10+ (for FastAPI backend)

---

## Starting the Application

### Backend (FastAPI)
Run the backend server from the project root directory:

```powershell
uvicorn backend.main:app --reload --port 8000
```
- **API Base URL**: `http://localhost:8000`
- **Swagger Documentation**: `http://localhost:8000/docs`

### Frontend (Angular)
Run the development server from the `frontend/` directory:

```powershell
cd frontend
npm start
```
- **Angular App URL**: `http://localhost:4200`
- The application automatically reloads on source code changes.

### Legacy Streamlit UI Note
- **Port 8501** (`http://localhost:8501`) belongs to the legacy Streamlit UI (`streamlit_app.py`).
- It should only be opened if Streamlit is deliberately launched. The primary UI is now the Angular application at `http://localhost:4200`.

---

## Assistant API Context & Polling Rules

1. **Context Requirement**:
   - The assistant requires an authenticated session (`x-session-token` or `session` cookie) and an authorized YouTube channel context (`selected_channel_id`).
   - Live stream polling for pending questions, live chat feed, suggestions, and superchats **only starts** when an active stream is connected (`state === 'LIVE'`).
2. **Gated Lifecycle**:
   - **Unauthenticated**: No polling occurs. User is redirected to `/login`.
   - **Authenticated, No Active Stream**: Only `/api/assistant/status` is checked. Live chat endpoints are not called, and the UI displays a clear empty state:
     `"Select a connected channel and active live stream to load the live assistant."`
   - **Active Live Stream (`LIVE`)**: Polling ticks every 3 seconds using RxJS `exhaustMap` to prevent request pile-ups.

---

## Troubleshooting & Diagnostics

### 422 Unprocessable Entity Errors
If an API request returns HTTP 422:
- Inspect request contract and payload schemas at `http://localhost:8000/docs`.
- Check DevTools Network tab -> **Response** tab to inspect FastAPI's exact validation error details (`loc`, `msg`, `type`).
- Ensure no required parameters (`channel_id`, `video_id`, `live_chat_id`, `question_key`) are sent as `undefined`, `null`, or empty strings.

### Browser Console Diagnostics
Development builds log safe diagnostic messages:
- `[API Diagnostic] GET /api/... -> Status 404: No active live chat found`
- Sensitive headers (`Authorization`), cookies, session tokens, and credentials are **never logged**.

---

## Dashboard Data-Flow & Architecture

```
┌───────────────────────────────┐
│     FastAPI Backend Endpoints │
│   (/api/assistant/feed, etc)  │
└───────────────┬───────────────┘
                │ Raw JSON DTOs (e.g. { author, text, score })
                ▼
┌───────────────────────────────┐
│     Explicit Mapping Layer    │
│ (core/models/assistant.models)│
│ mapFeedMessage, mapSuggestion │
└───────────────┬───────────────┘
                │ Clean View Models (e.g. ChatFeedItemVM, SuggestionItemVM)
                ▼
┌───────────────────────────────┐
│   AssistantService Signals    │
│  (recentMessages, suggestions)│
└───────────────┬───────────────┘
                │ Signal Selectors & Computed Filter Signals
                ▼
┌───────────────────────────────┐
│ Dashboard Component Templates │
│ (dashboard.component.html)    │
└───────────────────────────────┘
```

### Response Mapping Rules
- **Live Chat Feed**: Maps `author` -> `authorName`, `text` -> `messageText`, `sentiment` -> `sentimentLabel` (`positive`, `negative`, `neutral`).
- **Pending Questions Queue**: Maps `examples` or `question_key` -> `displayText`, preserving occurrence metadata (`authorName`, `text`, `timestamp`).
- **Suggestions & Confidence Categorization**:
  - **High Confidence ($\ge 80\%$)**: Match score $\ge 0.80$. Displays in the **High Confidence Suggestions** section. Eligible for auto-reply.
  - **Medium Confidence ($50\% - 79\%$)**: Match score $0.50 - 0.79$. Displays in the **Medium Confidence Suggestions** section for manual review.
- **Superchats**: Maps `author` -> `authorName`, `amount` -> `amountText`, `text` -> `messageText`.
