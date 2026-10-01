"""Groq AI assist: verify Q&A matches and draft answers — display-only.

OpenAI-compatible chat completions against Groq, default model
openai/gpt-oss-120b. The key comes from the environment; the project
.env is loaded via python-dotenv, which never overrides a variable that
is already set in the real environment.

Everything here is a suggestion for the streamer to review in the UI.
Nothing in this module posts to YouTube or writes to the Q&A memory —
saving and posting stay manual, per-click decisions.
"""

import os

import requests
from dotenv import load_dotenv

import qa_engine

load_dotenv()  # override=False: an existing environment variable wins

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-120b"
TIMEOUT_SECONDS = 20.0
NO_ANSWER = "NO_ANSWER"


def get_api_key():
    return os.environ.get("GROQ_API_KEY", "").strip()


def get_model():
    return os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_MODEL


def _context_block(records):
    lines = []
    for index, record in enumerate(records, 1):
        lines.append(f"{index}. Q: {record['normalized_question']}")
        lines.append(f"   A: {record['answer_text']}")
    return "\n".join(lines)


def _unavailable(note):
    return {"ok": False, "reliable": False, "answer": "", "note": note}


def review_question(question, suggested_answer=None, records=None, post=None):
    """Verify a proposed match, or draft an answer, from approved Q&A.

    Returns {"ok", "reliable", "answer", "note"}:
      ok=False          AI unavailable (no key, timeout, bad reply) — the
                        non-AI Jaccard flow is unaffected either way.
      ok, reliable=True answer is a grounded draft or verified answer.
      ok, reliable=False no reliable approved answer exists — answer "".
    """
    clean_question = str(question).strip()
    if not clean_question:
        return _unavailable("empty question")

    api_key = get_api_key()
    if not api_key:
        return _unavailable(
            "GROQ_API_KEY missing — add it to .env. "
            "Manual matching keeps working without it."
        )

    if records is None:
        records = [
            r for r in qa_engine.load_qa_data()
            if r.get("status") == "approved"
        ]
    context = _context_block(records) or "(no approved Q&A yet)"

    if suggested_answer:
        task = (
            "A word-matching algorithm proposes this existing answer: "
            f"\"{suggested_answer}\". Verify it against the notes: if it "
            "correctly answers the viewer question, reply with that answer "
            "(you may tighten the wording). If the notes do not support it, "
            f"reply with exactly {NO_ANSWER}."
        )
    else:
        task = (
            "Draft a short answer to the viewer question using only the "
            f"notes. If the notes do not answer it, reply with exactly {NO_ANSWER}."
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You assist a livestream host with viewer questions. Use "
                "ONLY the host's approved Q&A notes — never invent facts "
                "about the stream, gear, or host. Keep the answer under 200 "
                "characters (YouTube live-chat limit), plain text, no "
                f"sign-off. If the notes contain no reliable answer, reply "
                f"with exactly {NO_ANSWER}."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Host's approved Q&A notes:\n{context}\n\n"
                f"Viewer question: {clean_question}\n\n{task}"
            ),
        },
    ]

    if post is None:
        post = requests.post

    try:
        response = post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": get_model(),
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 300,
            },
            timeout=TIMEOUT_SECONDS,
        )
        content = response.json()["choices"][0]["message"]["content"]
    except requests.exceptions.Timeout:
        return _unavailable(f"Groq timed out after {TIMEOUT_SECONDS:.0f}s")
    except requests.exceptions.RequestException as error:
        return _unavailable(f"Groq request failed: {error}")
    except (KeyError, IndexError, TypeError, ValueError):
        return _unavailable("malformed response from Groq")

    answer = str(content or "").strip().strip('"').strip()
    if not answer or answer.strip(".!").upper().startswith(NO_ANSWER):
        return {
            "ok": True,
            "reliable": False,
            "answer": "",
            "note": "no reliable answer in the approved Q&A",
        }
    return {"ok": True, "reliable": True, "answer": answer, "note": ""}
