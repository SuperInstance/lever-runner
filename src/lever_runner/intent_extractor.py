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

import logging
import os
import re
from dataclasses import dataclass

import requests

log = logging.getLogger("lever-runner.intent")

DEFAULT_TIMEOUT_SEC = float(os.getenv("LLM_TIMEOUT_SEC", "5"))

# Default fallback chain. Comma-separated backends tried in order
# after the primary errors with a retryable condition. Empty string
# disables fallbacks. DeepInfra is the default because it's cheap,
# fast, and doesn't have the rate limits we've been hitting on
# MiniMax lately.
DEFAULT_FALLBACKS = "deepinfra"

# HTTP status codes that should trigger a fallback (transient
# provider-side problems). 4xx other than 429 are usually config bugs
# (bad key, model not found) and should propagate up so the operator
# can diagnose.
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504, 529}


def _is_retryable_http_error(e: requests.exceptions.HTTPError) -> bool:
    """True if the error's status code is a transient provider issue."""
    code = getattr(e.response, "status_code", None)
    return code in RETRYABLE_HTTP_STATUS


# Recognized backends and their default model + base URL. The list of
# recognized backends controls which `LLM_BACKEND=foo` values are valid
# without raising; the per-backend defaults only apply when the user
# hasn't overridden via LLM_MODEL / LLM_BASE_URL.
BACKEND_DEFAULTS: dict[str, dict[str, str]] = {
    "minimax": {
        "base_url": "https://api.minimax.io/anthropic",
        "model": "MiniMax-M3",
        "key_envs": "LLM_API_KEY,MINIMAX_API_KEY,ANTHROPIC_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "key_envs": "LLM_API_KEY,OPENAI_API_KEY",
    },
    "deepinfra": {
        "base_url": "https://api.deepinfra.com/v1/openai",
        # Default model: Llama-3.1-8B-Instruct. The Qwen3.5-4B
        # model on DeepInfra is a "reasoning" model that puts its
        # output in `reasoning_content` and leaves `content=""`,
        # so it can't be used as a phrase compressor. Llama 3.1 8B
        # is a clean instruction-follower at $0.02/M input,
        # $0.03/M output, with 128K context. Override via LLM_MODEL
        # for Qwen3-32B or Llama-4-Scout if quality is ever a
        # problem.
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
        "key_envs": "LLM_API_KEY,DEEPINFRA_API_KEY,DEEPINFRA_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434",
        "model": "llama3.1:8b-instruct-q4_K_M",
        "key_envs": "",
    },
    "passthrough": {
        "base_url": "",
        "model": "passthrough",
        "key_envs": "",
    },
}

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
    tokens_in: int  # approx input tokens sent to the LLM
    tokens_out: int  # approx output tokens returned
    backend: str


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------


def _approx_tokens(text: str) -> int:
    """Crude but consistent: ~1 token per 4 chars of English."""
    return max(1, len(text) // 4)


def _post_minimax_or_openai(
    base_url: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> str:
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
        r = requests.post(url, headers=headers, json=body, timeout=timeout_sec)
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
    r = requests.post(url, headers=headers, json=body, timeout=timeout_sec)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


def _post_ollama(
    host: str,
    model: str,
    system: str,
    user: str,
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
) -> str:
    url = host.rstrip("/") + "/api/chat"
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = requests.post(url, json=body, timeout=timeout_sec)
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


def _normalize(raw: str) -> str:
    """Tighten the LLM output to a clean phrase."""
    raw = raw.strip().strip("`'\"")
    raw = raw.splitlines()[0]  # first line only
    raw = raw.lower()
    raw = re.sub(r"[^a-z0-9 -]", "", raw)  # strip punctuation
    raw = re.sub(r"\s+", " ", raw).strip()
    # Truncate to the first ~8 words.
    words = raw.split()
    return " ".join(words[:8]) if words else ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract(
    user_request: str,
    *,
    backend: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Extraction:
    """Return a clean intent phrase plus token accounting."""
    backend = (backend or os.getenv("LLM_BACKEND", "minimax")).lower()
    user_request = (user_request or "").strip()
    if not user_request:
        return Extraction(phrase="", tokens_in=0, tokens_out=0, backend=backend)

    if backend == "passthrough":
        phrase = _normalize(user_request)
        return Extraction(phrase=phrase, tokens_in=0, tokens_out=0, backend=backend)

def _resolve_api_key(backend: str, explicit: str | None) -> tuple[str, list[str]]:
    """Return (api_key, key_env_list) for the given backend.

    Priority: explicit kwarg > LLM_API_KEY > backend's key_envs (first
    non-empty wins, not concatenated). Returns the list of env names
    checked for nicer error messages.
    """
    defaults = BACKEND_DEFAULTS.get(backend, BACKEND_DEFAULTS["minimax"])
    key_env_list = [e.strip() for e in defaults["key_envs"].split(",") if e.strip()]
    if explicit:
        return explicit.strip(), key_env_list
    generic = os.getenv("LLM_API_KEY", "").strip()
    if generic:
        return generic, key_env_list
    for e in key_env_list:
        v = os.getenv(e, "").strip()
        if v:
            return v, key_env_list
    return "", key_env_list


@dataclass
class _CallResult:
    raw: str
    tokens_in: int
    backend_used: str


def _try_one_backend(
    backend: str,
    system: str,
    user: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> _CallResult:
    """Make one LLM call to one backend. Returns the raw response text
    plus estimated input tokens. Raises on any HTTP / connection error;
    the caller is responsible for deciding what counts as retryable.

    Note: api_key, base_url, model kwargs override the per-backend
    defaults from BACKEND_DEFAULTS. This is useful for tests and for
    the fallback chain (which re-derives defaults from each backend's
    own metadata, not from the primary's env).
    """
    backend = backend.lower()
    defaults = BACKEND_DEFAULTS.get(backend)
    if defaults is None:
        raise ValueError(
            f"unknown LLM_BACKEND: {backend!r}. "
            f"Valid: {sorted(BACKEND_DEFAULTS.keys())}"
        )
    tokens_in = _approx_tokens(system) + _approx_tokens(user) + 8
    if backend == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        m = model or os.getenv("OLLAMA_MODEL", defaults["model"])
        raw = _post_ollama(host, m, system, user)
    else:
        # minimax / openai / deepinfra all use the same OpenAI or
        # Anthropic-shaped HTTP path.
        key, key_envs = _resolve_api_key(backend, api_key)
        if not key:
            raise RuntimeError(
                f"no API key for LLM_BACKEND={backend!r}; set one of: "
                f"LLM_API_KEY, {', '.join(key_envs)} in the environment, "
                f"or use LLM_BACKEND=passthrough"
            )
        # URL/model resolution. The `base_url` and `model` kwargs
        # are what the caller (extract's fallback chain) wants to
        # apply *to this specific attempt*. If they're None, we
        # use the per-backend default.
        #
        # We deliberately do NOT honor the global LLM_BASE_URL /
        # LLM_MODEL env vars here. Those are set for the primary
        # backend and would otherwise leak into fallback attempts
        # (e.g. primary's minimax URL being sent to deepinfra). If
        # the operator wants to point a specific backend elsewhere,
        # they should set per-backend env vars
        # (LLM_<BACKEND>_BASE_URL, LLM_<BACKEND>_MODEL) or pass the
        # kwargs explicitly.
        per_backend_url_env = f"LLM_{backend.upper()}_BASE_URL"
        per_backend_model_env = f"LLM_{backend.upper()}_MODEL"
        if base_url is None:
            base_url = os.getenv(per_backend_url_env) or defaults["base_url"]
        if model is None:
            model = os.getenv(per_backend_model_env) or defaults["model"]
        raw = _post_minimax_or_openai(base_url, key, model, system, user)
    return _CallResult(raw=raw, tokens_in=tokens_in, backend_used=backend)


def _passthrough_fallback(user_request: str) -> Extraction:
    """Final fallback: the user's raw request is the intent phrase."""
    return Extraction(
        phrase=_normalize(user_request),
        tokens_in=0,
        tokens_out=0,
        backend="passthrough-fallback",
    )


def _resolve_fallback_chain(primary: str) -> list[str]:
    """Read LLM_FALLBACKS and return a list of fallback backends.

    'passthrough' is always appended as the last resort. The primary
    is excluded from the list (it's tried first anyway). Unknown
    backends are filtered out and logged.
    """
    raw = os.getenv("LLM_FALLBACKS", DEFAULT_FALLBACKS)
    chain = [b.strip().lower() for b in raw.split(",") if b.strip()]
    chain = [b for b in chain if b != primary]
    valid = set(BACKEND_DEFAULTS.keys()) | {"passthrough"}
    filtered = []
    for b in chain:
        if b in valid:
            filtered.append(b)
        else:
            log.warning("ignoring unknown LLM_FALLBACKS entry: %r", b)
    if "passthrough" not in filtered:
        filtered.append("passthrough")
    return filtered


def extract(
    user_request: str,
    *,
    backend: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> Extraction:
    """Return a clean intent phrase plus token accounting.

    Calls the primary LLM_BACKEND first; on a retryable error (timeout,
    connection refused, 429, 5xx) it tries each entry in LLM_FALLBACKS
    in order. The last entry is always 'passthrough' so a complete
    provider outage degrades to using the raw user request as the
    intent (rather than hanging or 5xxing the user).
    """
    backend = (backend or os.getenv("LLM_BACKEND", "minimax")).lower()
    user_request = (user_request or "").strip()
    if not user_request:
        return Extraction(phrase="", tokens_in=0, tokens_out=0, backend=backend)

    if backend == "passthrough":
        phrase = _normalize(user_request)
        return Extraction(phrase=phrase, tokens_in=0, tokens_out=0, backend=backend)

    system = SYSTEM_PROMPT
    user = user_request

    # Build the full chain: primary first, then fallbacks (passthrough last).
    fallback_chain = _resolve_fallback_chain(backend)
    full_chain = [backend] + fallback_chain

    last_error: Exception | None = None
    # The primary's base_url/model kwargs come from the caller. For
    # attempt 0 we also honor LLM_BASE_URL / LLM_MODEL as a
    # convenience (the operator usually sets them globally). For
    # fallbacks (attempt > 0) we deliberately let `_try_one_backend`
    # use the per-backend defaults so the primary's URL doesn't leak.
    if base_url is None:
        base_url = os.getenv("LLM_BASE_URL")
    if model is None:
        model = os.getenv("LLM_MODEL")
    for attempt, current_backend in enumerate(full_chain):
        if current_backend == "passthrough":
            log.info("LLM: giving up after %d attempt(s); using passthrough fallback", attempt)
            return _passthrough_fallback(user_request)
        try:
            result = _try_one_backend(
                current_backend, system, user,
                api_key=api_key if attempt == 0 else None,
                base_url=base_url if attempt == 0 else None,
                model=model if attempt == 0 else None,
            )
            if attempt > 0:
                log.info("LLM: primary %r failed; succeeded on fallback %r", backend, current_backend)
            phrase = _normalize(result.raw)
            tokens_out = _approx_tokens(result.raw) + 2
            return Extraction(
                phrase=phrase,
                tokens_in=result.tokens_in,
                tokens_out=tokens_out,
                backend=result.backend_used,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            log.warning("LLM: backend %r attempt %d failed: %s", current_backend, attempt + 1, e)
            continue
        except requests.exceptions.HTTPError as e:
            last_error = e
            code = getattr(e.response, "status_code", None)
            if _is_retryable_http_error(e):
                log.warning("LLM: backend %r attempt %d failed: HTTP %s", current_backend, attempt + 1, code)
                continue
            # 401 means this provider's key is bad/expired. In a
            # chain context, that's a reason to skip to the next
            # backend (the next provider may have a valid key).
            # 4xx other than 401 (400, 404, etc.) are usually bugs
            # in the request itself (bad model name, malformed body)
            # and would fail the same way on any provider, so we
            # propagate them up so the operator can diagnose.
            if code == 401 and len(full_chain) > attempt + 1:
                log.warning("LLM: backend %r returned HTTP 401; skipping to next backend", current_backend)
                continue
            log.error("LLM: backend %r returned non-retryable HTTP %s; not falling back", current_backend, code)
            raise
        except RuntimeError as e:
            # Missing API key for this backend. Skip to next.
            last_error = e
            log.warning("LLM: backend %r not configured: %s", current_backend, e)
            continue

    # If we get here, every attempt failed in a way the chain handled.
    log.error("LLM: all %d attempts failed; last error: %r", len(full_chain), last_error)
    return _passthrough_fallback(user_request)
