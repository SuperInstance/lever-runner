"""
intent_extractor.py — turn a user request into a short intent phrase + args.

The LLM is asked to do one thing and one thing only: compress a sentence
into a 3-8 word phrase and optionally extract key=value arguments. No tool
schemas, no chain-of-thought, no examples beyond what fits in ~80 input
tokens.

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

def _timeout_sec() -> float:
    """Return the current LLM timeout from env (dynamic so tests can override at runtime)."""
    return float(os.getenv("LLM_TIMEOUT_SEC", "5"))

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
    "If the request names a specific thing (container, service, port, file, etc.), "
    "replace it with the appropriate generic word in the phrase. "
    "Examples:\n"
    "  'can you check how much disk I have left?' -> show disk usage\n"
    "  'restart nginx' -> restart service\n"
    "  'show logs for nginx' -> show logs for container\n"
    "  'check port 8080' -> check port\n"
    "\nOn the next line, output extracted arguments as key=value pairs, "
    "one per line: arg_name=value. Only extract arguments that "
    "correspond to generic words you used. If no arguments, output nothing.\n"
    "Examples:\n"
    "  'show logs for nginx' -> show logs for container\n"
    "                          container=nginx\n"
    "  'check disk usage' -> show disk usage\n"
)

INTENT_RE = re.compile(r"[a-z][a-z0-9 -]{2,60}")


@dataclass
class Extraction:
    phrase: str
    tokens_in: int  # approx input tokens sent to the LLM
    tokens_out: int  # approx output tokens returned
    backend: str
    args: dict | None = None  # extracted arguments for parameterized commands


def _parse_args(raw: str) -> dict[str, str]:
    """Parse key=value pairs from LLM output. Returns an empty dict if none found."""
    args: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key and val and key.isidentifier():
                args[key] = val
    return args


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
    timeout_sec: float = _timeout_sec(),
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
            "max_tokens": 48,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        r = requests.post(url, headers=headers, json=body, timeout=timeout_sec)
        r.raise_for_status()
        data = r.json()
        content = data.get("content", [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block_type = block.get("type", "")
                    if block_type == "text":
                        return block.get("text", "").strip()
                elif isinstance(block, str):
                    return block.strip()
        if isinstance(content, str):
            return content.strip()
        if content:
            block = content[0]
            if isinstance(block, dict):
                return str(block.get("text", block.get("content", str(block)))).strip()
            if isinstance(block, str):
                return block.strip()
        raise ValueError(f"unexpected Anthropic response: content={content!r}")

    # OpenAI-compatible fallback
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 48,
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
    timeout_sec: float = _timeout_sec(),
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


def _normalize(raw: str) -> tuple[str, dict[str, str]]:
    """Tighten the LLM output to a clean phrase and extract key=value args.

    The LLM outputs the intent phrase on the first line, optionally
    followed by key=value argument lines.

    Returns (phrase, args).
    """
    raw = raw.strip().strip("`'\"")
    lines = raw.splitlines()
    # First line is the phrase
    phrase_line = lines[0] if lines else ""
    phrase_line = phrase_line.lower()
    phrase_line = re.sub(r"[^a-z0-9 -]", "", phrase_line)
    phrase_line = re.sub(r"\s+", " ", phrase_line).strip()
    words = phrase_line.split()
    phrase = " ".join(words[:8]) if words else ""
    # Remaining lines may contain key=value args
    args = _parse_args("\n".join(lines[1:])) if len(lines) > 1 else {}
    return phrase, args


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _resolve_api_key(backend: str, explicit: str | None) -> tuple[str, list[str]]:
    """Return (api_key, key_env_list) for the given backend."""
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
    plus estimated input tokens. Raises on any HTTP / connection error.
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
        key, key_envs = _resolve_api_key(backend, api_key)
        if not key:
            raise RuntimeError(
                f"no API key for LLM_BACKEND={backend!r}; set one of: "
                f"LLM_API_KEY, {', '.join(key_envs)} in the environment, "
                f"or use LLM_BACKEND=passthrough"
            )
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
    phrase, args = _normalize(user_request)
    return Extraction(
        phrase=phrase,
        tokens_in=0,
        tokens_out=0,
        backend="passthrough-fallback",
        args=args if args else None,
    )


def _resolve_fallback_chain(primary: str) -> list[str]:
    """Read LLM_FALLBACKS and return a list of fallback backends."""
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
    """Return a clean intent phrase, extracted args, plus token accounting.

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
        phrase, args = _normalize(user_request)
        return Extraction(
            phrase=phrase, tokens_in=0, tokens_out=0,
            backend=backend, args=args if args else None,
        )

    system = SYSTEM_PROMPT
    user = user_request

    # Build the full chain: primary first, then fallbacks (passthrough last).
    fallback_chain = _resolve_fallback_chain(backend)
    full_chain = [backend] + fallback_chain

    last_error: Exception | None = None
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
            phrase, args = _normalize(result.raw)
            tokens_out = _approx_tokens(result.raw) + 2
            return Extraction(
                phrase=phrase,
                tokens_in=result.tokens_in,
                tokens_out=tokens_out,
                backend=result.backend_used,
                args=args if args else None,
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
            if code == 401 and len(full_chain) > attempt + 1:
                log.warning("LLM: backend %r returned HTTP 401; skipping to next backend", current_backend)
                continue
            log.error("LLM: backend %r returned non-retryable HTTP %s; not falling back", current_backend, code)
            raise
        except RuntimeError as e:
            last_error = e
            log.warning("LLM: backend %r not configured: %s", current_backend, e)
            continue

    log.error("LLM: all %d attempts failed; last error: %r", len(full_chain), last_error)
    return _passthrough_fallback(user_request)
