"""Direct, controlled smoke test for Groq and NVIDIA reviewers.

Limits & Constraints:
- Exactly 2 requests per provider (4 requests total).
- Retries disabled (0 retries).
- Fallback disabled.
- Zero credential logging or printing.
- No YouTube posting, Q&A modification, or index change.
- Captures HTTP status, latency, tokens, finish reason, and truncation checks.
- Stops provider immediately on authentication error (HTTP 401/403).
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from dotenv import load_dotenv

load_dotenv()

from backend.review_service import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_NVIDIA_MODEL,
    GROQ_URL,
    NVIDIA_URL,
    build_review_messages,
    parse_review_response,
)

SMOKE_CASES = [
    {
        "case_id": "SMOKE_REL_01",
        "description": "Relevant Pair (Hinglish)",
        "viewer_question": "Stream kab shuru hoti hai?",
        "candidate_question": "What time do streams start?",
        "candidate_answer": "Daily at 8:00 PM IST.",
        "expected_verdict": "accept",
    },
    {
        "case_id": "SMOKE_IRREL_01",
        "description": "Irrelevant Pair (Price vs Model)",
        "viewer_question": "Camera kitne ka hai?",
        "candidate_question": "Which camera do you use?",
        "candidate_answer": "Sony ZV-E10 with Sigma 16mm f/1.4 lens.",
        "expected_verdict": "reject",
    },
]


def execute_single_request(
    provider: str,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a single HTTP request with retries disabled and capture metrics."""
    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        model = os.environ.get("GROQ_MODEL", "").strip() or DEFAULT_GROQ_MODEL
        url = GROQ_URL
    elif provider == "nvidia":
        api_key = os.environ.get("NVIDIA_API_KEY", "").strip()
        model = os.environ.get("NVIDIA_MODEL", "").strip() or DEFAULT_NVIDIA_MODEL
        url = NVIDIA_URL
    else:
        raise ValueError(f"Unknown provider {provider}")

    if not api_key:
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": None,
            "latency_ms": 0.0,
            "tokens": None,
            "finish_reason": None,
            "error_type": "auth",
            "reason": f"Missing API key for {provider}",
        }

    messages = build_review_messages(
        viewer_question=case["viewer_question"],
        candidate_question=case["candidate_question"],
        candidate_answer=case["candidate_answer"],
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": 60,
    }

    t0 = time.perf_counter()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10.0)
        dur_ms = (time.perf_counter() - t0) * 1000
    except requests.exceptions.Timeout:
        dur_ms = (time.perf_counter() - t0) * 1000
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": None,
            "latency_ms": round(dur_ms, 2),
            "tokens": None,
            "finish_reason": None,
            "error_type": "timeout",
            "reason": "Request timed out after 10.0s",
        }
    except requests.exceptions.RequestException as exc:
        dur_ms = (time.perf_counter() - t0) * 1000
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": None,
            "latency_ms": round(dur_ms, 2),
            "tokens": None,
            "finish_reason": None,
            "error_type": "http",
            "reason": f"Network exception: {exc}",
        }

    http_status = resp.status_code

    if http_status in (401, 403):
        try:
            err_msg = resp.json().get("error", {}).get("message", f"HTTP {http_status}")
        except Exception:
            err_msg = f"HTTP {http_status}"
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": http_status,
            "latency_ms": round(dur_ms, 2),
            "tokens": None,
            "finish_reason": None,
            "error_type": "auth",
            "reason": f"Authentication failed: {err_msg}",
        }

    if http_status != 200:
        try:
            err_msg = resp.json().get("error", {}).get("message", f"HTTP {http_status}")
        except Exception:
            err_msg = f"HTTP {http_status}"
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": http_status,
            "latency_ms": round(dur_ms, 2),
            "tokens": None,
            "finish_reason": None,
            "error_type": "http",
            "reason": f"Upstream HTTP error ({http_status}): {err_msg}",
        }

    try:
        data = resp.json()
    except Exception as exc:
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": http_status,
            "latency_ms": round(dur_ms, 2),
            "tokens": None,
            "finish_reason": None,
            "error_type": "parsing",
            "reason": f"JSON decode failed: {exc}",
        }

    usage = data.get("usage")
    tokens_info = None
    if usage and isinstance(usage, dict):
        tokens_info = {
            "prompt": usage.get("prompt_tokens"),
            "completion": usage.get("completion_tokens"),
            "total": usage.get("total_tokens"),
        }

    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": http_status,
            "latency_ms": round(dur_ms, 2),
            "tokens": tokens_info,
            "finish_reason": None,
            "error_type": "parsing",
            "reason": "Missing or empty choices list",
        }

    first_choice = choices[0]
    finish_reason = first_choice.get("finish_reason")
    raw_content = first_choice.get("message", {}).get("content", "")

    # Output truncation guard
    if finish_reason == "length":
        return {
            "case_id": case["case_id"],
            "provider": provider,
            "model": model,
            "expected_verdict": case["expected_verdict"],
            "actual_verdict": "unavailable",
            "http_status": http_status,
            "latency_ms": round(dur_ms, 2),
            "tokens": tokens_info,
            "finish_reason": finish_reason,
            "error_type": "truncated",
            "reason": "Output truncated by max_tokens limit (finish_reason=length)",
        }

    # Parse and validate structured outcome
    parsed = parse_review_response(
        raw_content=raw_content,
        provider=provider,
        model=model,
        candidate_answer=case["candidate_answer"],
        latency_ms=dur_ms,
    )

    return {
        "case_id": case["case_id"],
        "provider": provider,
        "model": model,
        "expected_verdict": case["expected_verdict"],
        "actual_verdict": parsed.outcome,
        "http_status": http_status,
        "latency_ms": round(dur_ms, 2),
        "tokens": tokens_info,
        "finish_reason": finish_reason,
        "error_type": parsed.error_type,
        "reason": parsed.reason,
    }


def run_smoke_test() -> List[Dict[str, Any]]:
    results = []

    for provider in ("groq", "nvidia"):
        print(f"\n--- Running smoke test for: {provider.upper()} ---")
        for case in SMOKE_CASES:
            print(f"Testing {case['case_id']} ({case['description']})...")
            res = execute_single_request(provider, case)
            results.append(res)
            print(f"  Result: status={res['http_status']}, verdict={res['actual_verdict']}, latency={res['latency_ms']}ms")

            # Check if authentication error: stop further tests for this provider
            if res.get("error_type") == "auth":
                print(f"  [STOP] Authentication error encountered for {provider}. Halting further requests for this provider.")
                break

    return results


if __name__ == "__main__":
    test_results = run_smoke_test()
    print("\n" + json.dumps(test_results, indent=2))
