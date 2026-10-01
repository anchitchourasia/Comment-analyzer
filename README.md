# YouTube Comment & Live Chat Analyzer

A Streamlit web app that pulls comments and live-chat messages from YouTube and classifies their sentiment, plus a creator-approved Q&A matcher prototype.

## Features

- **Video Comments tab** — enter a video ID, fetch up to 1,000 public comments, see them bucketed Positive / Negative / Neutral with VADER sentiment scores.
- **Live Chat tab** — analyze the latest text messages of an active livestream the same way.
- **Q&A Prototype tab** — creators store approved answers locally; viewer questions are matched by token overlap (exact match scores 1.0) with a confidence score.

## How It Works

```text
YouTube Data API v3 (video ID / live-chat ID)
      ↓
Fetch comments / chat messages
      ↓
Clean text (strip URLs, punctuation)
      ↓
NLTK VADER sentiment → Positive / Negative / Neutral
      ↓
Streamlit dashboard (counts per category, per-message scores)
```

The Q&A tab is rule-based word-overlap matching. It stores approved question-answer pairs in a local `qa_data.json` file and does not post anything back to YouTube.

## Setup

Requires Python 3.9+.

```bash
git clone https://github.com/anchitchourasia/Comment-analyzer.git
cd Comment-analyzer
pip install -r requirements.txt
mkdir .streamlit
echo 'YOUTUBE_API_KEY = "<your key>"' > .streamlit/secrets.toml
```

Get a YouTube Data API v3 key from the
[Google Cloud Console](https://console.cloud.google.com/).
Create the API credential yourself — never commit a key to the repository.

## Run

```bash
streamlit run streamlit_app.py
```

For the Live Chat tab you need the livestream's chat ID, not the video ID.
Generate it while the stream is active:

```bash
set YOUTUBE_API_KEY=<your key>   # Windows
python livechat_id_generator.py
```

## Tests

```bash
python test_qa_engine.py
```

## Configuration

| Item | Where | Notes |
| --- | --- | --- |
| `YOUTUBE_API_KEY` | `.streamlit/secrets.toml` | Used by the Streamlit app. Gitignored. |
| `YOUTUBE_API_KEY` | environment variable | Used by `livechat_id_generator.py`. |
| `qa_data.json` | repo root | Runtime Q&A storage. Created on first save. Gitignored. |

## Author

Created and maintained by [anchitchourasia](https://github.com/anchitchourasia).
