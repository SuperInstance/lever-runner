"""
intent_extractor.py — turn a user request into a short intent phrase.

The LLM is asked to do one thing and one thing only: compress a sentence
into a 3-8 word phrase. No tool schemas, no chain-of-thought, no examples
beyond what fits in ~60 input tokens.

Backends:
    - "minimax"   : Anthropic-compatible HTTP API (default; hosted MiniMax-M3)
    - "openai"    : OpenAI-compatible HTTP API
    - "ollama"    : local Ollama (off by default on this host)
    - "passthrough": the request *is* the intent phrase; no LLM call

Token accounting is approximate (the local Ollama tokenizer is the
sentencepiece fallback; hosted APIs are not introspected for exact counts).
This is good enough for the < 200 tokens/command benchmark.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

import requests


SYSTEM_PROMPT = (
    "You compress a user request into a short verb-noun phrase of 3-8 words. "
    "Output ONLY the phrase, lowercase, no punctuation, no quotes, no prefix. "
    "Examples:\n"
    "  'can you check how much disk I have left?' -> show disk usage\n"
    "  'restart nginx' -> restart nginx\n"
    "  'what's eating my CPU?' -> show top cpu processes\n"
)

INTENT_RE = re.compile(r"[a-z][a-z0-9 -]{2,60}")


@dataclass
class Extraction:
    phrase: str
    tokens_in: int        # approx input tokens sent to the LLM
    tokens_out: int       # approx output tokens returned
    backend: str


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    """Crude but consistent: ~1 token per 4 chars of English."""
    return max(1, len(text) // 4)


def _post_minimax_or_openai(base_url: str, api_key: str, model: str,
                            system: str, user: str) -> str:
    """Call any Anthropic-compatible or OpenAI-compatible chat endpoint."""
    # Detect the wire format. MiniMax exposes /v1/messages (Anthropic).
    is_anthropic = base_url.rstrip("/").endswith("/anthropic") or "/anthropic" in base_url
    if is_anthropic:
        url = base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": model,
            "max_tokens": 32,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        r = requests.post(url, headers=headers, json=body, timeout=30)
        r.raise_for_status()
        data = r.json()
        # Anthropic: content[0].text
        return data["content"][0]["text"].strip()

    # OpenAI-compatible fallback
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 32,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


def _post_ollama(host: str, model: str, system: str, user: str) -> str:
    url = host.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = requests.post(url, json=body, timeout=30)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def _normalize(raw: str) -> str:
    """Tighten the LLM output to a clean phrase."""
    raw = raw.strip().strip("`'\"")
    raw = raw.splitlines()[0]                  # first line only
    raw = raw.lower()
    raw = re.sub(r"[^a-z0-9 -]", "", raw)      # strip punctuation
    raw = re.sub(r"\s+", " ", raw).strip()
    # Truncate to the first ~8 words.
    words = raw.split()
    return " ".join(words[:8]) if words else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract(user_request: str, *,
            backend: Optional[str] = None,
            api_key: Optional[str] = None,
            base_url: Optional[str] = None,
            model: Optional[str] = None) -> Extraction:
    """Return a clean intent phrase plus token accounting."""
    backend = (backend or os.getenv("LLM_BACKEND", "minimax")).lower()
    user_request = (user_request or "").strip()
    if not user_request:
        return Extraction(phrase="", tokens_in=0, tokens_out=0, backend=backend)

    if backend == "passthrough":
        phrase = _normalize(user_request)
        return Extraction(phrase=phrase, tokens_in=0, tokens_out=0, backend=backend)

    system = SYSTEM_PROMPT
    user = user_request
    tokens_in = _approx_tokens(system) + _approx_tokens(user) + 8  # +overhead

    if backend in ("minimax", "openai"):
        api_key = (
            api_key
            or os.getenv("LLM_API_KEY", "")
            or os.getenv("MINIMAX_API_KEY", "")
            or os.getenv("ANTHROPIC_API_KEY", "")
            or os.getenv("OPENAI_API_KEY", "")
        )
        base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.minimax.io/anthropic")
        model = model or os.getenv("LLM_MODEL", "MiniMax-M3")
        if not api_key:
            raise RuntimeError(
                "no API key found; set LLM_API_KEY, MINIMAX_API_KEY, "
                "ANTHROPIC_API_KEY, or OPENAI_API_KEY in the environment, "
                "or use LLM_BACKEND=passthrough"
            )
        raw = _post_minimax_or_openai(base_url, api_key, model, system, user)
    elif backend == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        model = model or os.getenv("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
        raw = _post_ollama(host, model, system, user)
    else:
        raise ValueError(f"unknown LLM_BACKEND: {backend!r}")

    phrase = _normalize(raw)
    tokens_out = _approx_tokens(raw) + 2
    return Extraction(phrase=phrase, tokens_in=tokens_in, tokens_out=tokens_out, backend=backend)
