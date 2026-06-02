"""
token_logger.py — append-only JSONL token usage log.

One line per LLM call and one per embedding call. The benchmark script
parses this file to compute average tokens/command.

Rotation: size-based, configurable. Default is 5 MiB per file with up
to 3 backups (so a max of ~20 MiB on disk per log). Rotation is
triggered before each write, so the check is cheap and the file
handle stays under stdlib control.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

LOG_PATH = os.getenv("TOKEN_LOG_PATH", "./logs/token_usage.jsonl")
EMBED_LOG_PATH = os.getenv("EMBED_LOG_PATH", "./logs/embed_usage.jsonl")
# Rotation thresholds. Override via env if a deployment has a much
# higher or lower LLM call rate.
LOG_MAX_BYTES = int(os.getenv("TOKEN_LOG_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MiB
LOG_BACKUP_COUNT = int(os.getenv("TOKEN_LOG_BACKUP_COUNT", "3"))


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


def _rotate_if_needed(path: str, max_bytes: int, backup_count: int) -> None:
    """If `path` exceeds max_bytes, rotate: name -> name.1, .1 -> .2, etc.

    Keeps at most `backup_count` backups; the oldest is dropped.
    This is a small reimplementation of RotatingFileHandler to avoid
    holding a long-lived file handle inside a stateless helper.
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        if p.stat().st_size < max_bytes:
            return
    except OSError:
        return
    # Drop the oldest backup if it would exceed backup_count
    oldest = p.with_suffix(p.suffix + f".{backup_count}")
    if oldest.exists():
        try:
            oldest.unlink()
        except OSError:
            pass
    # Shift .N -> .(N+1) for N = backup_count-1 down to 1
    for n in range(backup_count - 1, 0, -1):
        src = p.with_suffix(p.suffix + f".{n}")
        dst = p.with_suffix(p.suffix + f".{n + 1}")
        if src.exists():
            try:
                src.replace(dst)
            except OSError:
                pass
    # Move the live file to .1
    try:
        p.replace(p.with_suffix(p.suffix + ".1"))
    except OSError:
        # If the rename fails (e.g. file was just removed by another
        # writer), just truncate and move on; we lose history for this
        # rotation cycle but the next call will be fine.
        pass


def _append(path: str, record: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _rotate_if_needed(path, LOG_MAX_BYTES, LOG_BACKUP_COUNT)
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
