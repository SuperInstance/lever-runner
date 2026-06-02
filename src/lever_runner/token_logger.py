"""
token_logger.py — append-only JSONL token usage log.

One line per LLM call and one per embedding call. The benchmark script
parses this file to compute average tokens/command.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

LOG_PATH = os.getenv("TOKEN_LOG_PATH", "./logs/token_usage.jsonl")
EMBED_LOG_PATH = os.getenv("EMBED_LOG_PATH", "./logs/embed_usage.jsonl")


@dataclass
class TokenRecord:
    ts: float
    kind: str  # "intent" or "embed"
    backend: str
    tokens_in: int
    tokens_out: int
    total: int
    source: str  # chat_id, "cli", or "http"
    extra: dict | None = None


def _append(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_intent(backend: str, tokens_in: int, tokens_out: int, source: str) -> None:
    _append(
        LOG_PATH,
        asdict(
            TokenRecord(
                ts=time.time(),
                kind="intent",
                backend=backend,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                total=tokens_in + tokens_out,
                source=source,
            )
        ),
    )


def log_embed(text: str, source: str) -> None:
    """Approximate embedding token accounting. all-MiniLM-L6-v2 tokenizes
    with a WordPiece vocab; we count ~1 token per 0.75 words."""
    n_words = max(1, len(text.split()))
    tokens = int(n_words / 0.75) + 2
    _append(
        EMBED_LOG_PATH,
        {
            "ts": time.time(),
            "kind": "embed",
            "text_len": len(text),
            "tokens": tokens,
            "source": source,
        },
    )
