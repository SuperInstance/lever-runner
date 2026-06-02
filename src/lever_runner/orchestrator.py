"""
orchestrator.py — single dispatcher for /do, /teach, /status.

Three front-ends call into it:
    - bot.py            : Telegram adapter (python-telegram-bot)
    - cli.py            : `python -m lever_runner "check disk usage"`
    - http_api.py       : POST /run {"request": "..."}
"""

from __future__ import annotations

from dataclasses import dataclass

from . import token_logger
from .executor import RunResult, run_command
from .intent_extractor import extract as extract_intent
from .store import CommandStore, Match


@dataclass
class DoResult:
    ok: bool
    user_request: str
    intent: str
    match: Match | None
    run: RunResult | None
    tokens_in: int
    tokens_out: int
    error: str | None = None
    no_match: bool = False

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


def do(
    user_request: str,
    *,
    source: str = "cli",
    chat_id: str = "default",
    store: CommandStore | None = None,
    min_trust: float = 40.0,
    auto_run: bool = True,
) -> DoResult:
    """End-to-end: extract intent → embed → find best → optionally run.

    chat_id scopes the store to a per-chat table. Defaults to "default"
    for CLI usage. The Telegram bot passes str(update.effective_chat.id).
    """
    store = store or CommandStore(chat_id=chat_id)

    extraction = extract_intent(user_request)
    token_logger.log_intent(
        extraction.backend, extraction.tokens_in, extraction.tokens_out, source=source
    )
    token_logger.log_embed(extraction.phrase, source=source)

    if not extraction.phrase:
        return DoResult(
            ok=False,
            user_request=user_request,
            intent="",
            match=None,
            run=None,
            tokens_in=extraction.tokens_in,
            tokens_out=extraction.tokens_out,
            error="LLM returned an empty intent phrase",
        )

    matches = store.find_best(extraction.phrase, top_k=3)
    if not matches:
        return DoResult(
            ok=False,
            user_request=user_request,
            intent=extraction.phrase,
            match=None,
            run=None,
            tokens_in=extraction.tokens_in,
            tokens_out=extraction.tokens_out,
            no_match=True,
            error="no commands in the table yet — run init_db.py",
        )

    # Pick the match with the best similarity (lowest L2 distance) that
    # is also at or above the trust floor. Trust is a *gate*, not a
    # tiebreaker for similar matches: once two candidates are both above
    # the floor, the one whose embedding is closest to the user's
    # intent wins. Falls back to top-1 by similarity if all matches are
    # below the trust floor.
    eligible = [m for m in matches if m.trust_score >= min_trust] or matches[:1]
    chosen = min(eligible, key=lambda m: m.score)

    # Confidence check: if the best match's cosine similarity is below the
    # floor, treat it as no-match and surface the candidates for /teach.
    # (Falls back to the global env var, then 0.55 as a sane default for
    # MiniLM-L6-v2 with normalized embeddings.)
    import os as _os

    sim_floor = float(_os.getenv("MATCH_SIMILARITY_FLOOR", "0.55"))
    if chosen.similarity < sim_floor:
        return DoResult(
            ok=False,
            user_request=user_request,
            intent=extraction.phrase,
            match=chosen,
            run=None,
            tokens_in=extraction.tokens_in,
            tokens_out=extraction.tokens_out,
            no_match=True,
            error=(
                f"best match below similarity floor "
                f"({chosen.similarity:.2f} < {sim_floor:.2f}); "
                f"use /teach to add this command"
            ),
        )

    if not auto_run:
        return DoResult(
            ok=True,
            user_request=user_request,
            intent=extraction.phrase,
            match=chosen,
            run=None,
            tokens_in=extraction.tokens_in,
            tokens_out=extraction.tokens_out,
        )

    result = run_command(chosen.command)
    store.update_trust(chosen.id, success=result.ok)
    return DoResult(
        ok=result.ok,
        user_request=user_request,
        intent=extraction.phrase,
        match=chosen,
        run=result,
        tokens_in=extraction.tokens_in,
        tokens_out=extraction.tokens_out,
    )


def teach(
    intent_phrase: str,
    command: str,
    *,
    chat_id: str = "default",
    store: CommandStore | None = None,
) -> str:
    store = store or CommandStore(chat_id=chat_id)
    return store.teach(intent_phrase, command)


def status(chat_id: str = "default", *, store: CommandStore | None = None) -> dict:
    store = store or CommandStore(chat_id=chat_id)
    return {"command_count": store.count(), "chat_id": chat_id}
