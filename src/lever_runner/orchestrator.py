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
from .fastloop_bridge import FastLoopBridge
from .intent_extractor import extract as extract_intent
from .store import CommandStore, Match, has_placeholders, substitute_args

# Module-level fast-loop bridge (Rust UDS with Python fallback)
_fastloop = FastLoopBridge()


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
    args: dict | None = None  # extracted arguments for parameterized commands

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
    """End-to-end: extract intent + args → embed → find best → substitute → optionally run.

    chat_id scopes the store to a per-chat table. Defaults to "default"
    for CLI usage. The Telegram bot passes str(update.effective_chat.id).
    """
    store = store or CommandStore(chat_id=chat_id)

    # ── Fast-Loop: sub-ms validation before any LLM call ──
    fl_result = _fastloop.check(user_request, context="", sandbox_id=chat_id)
    if fl_result.action == "ROUTE_TO_DEEP_LOOP":
        return DoResult(
            ok=False,
            user_request=user_request,
            intent="",
            match=None,
            run=None,
            tokens_in=0,
            tokens_out=0,
            error=f"fast-loop blocked: {fl_result.reason}",
        )
    # ── End Fast-Loop ──

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
    # is also at or above the trust floor.
    eligible = [m for m in matches if m.trust_score >= min_trust] or matches[:1]
    chosen = min(eligible, key=lambda m: m.score)

    # Confidence check
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

    # Determine the command to execute
    command = chosen.command
    extracted_args = extraction.args

    # If the matched command is a template (has {{param}} placeholders),
    # substitute the extracted args
    if has_placeholders(command):
        if extracted_args:
            try:
                command = substitute_args(command, extracted_args)
            except ValueError as e:
                return DoResult(
                    ok=False,
                    user_request=user_request,
                    intent=extraction.phrase,
                    match=chosen,
                    run=None,
                    tokens_in=extraction.tokens_in,
                    tokens_out=extraction.tokens_out,
                    error=f"argument substitution failed: {e}",
                    args=extracted_args,
                )
        else:
            # Template command but no args extracted — can't execute
            from .store import get_placeholders
            placeholders = get_placeholders(command)
            return DoResult(
                ok=False,
                user_request=user_request,
                intent=extraction.phrase,
                match=chosen,
                run=None,
                tokens_in=extraction.tokens_in,
                tokens_out=extraction.tokens_out,
                error=(
                    f"this command requires arguments: "
                    f"{', '.join(placeholders)}. "
                    f"Try e.g. '{user_request} with <value>'"
                ),
                args=None,
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
            args=extracted_args,
        )

    result = run_command(command)
    store.update_trust(chosen.id, success=result.ok)
    return DoResult(
        ok=result.ok,
        user_request=user_request,
        intent=extraction.phrase,
        match=chosen,
        run=result,
        tokens_in=extraction.tokens_in,
        tokens_out=extraction.tokens_out,
        args=extracted_args,
    )


def teach(
    intent_phrase: str,
    command: str,
    *,
    chat_id: str = "default",
    trust: float | None = None,
    store: CommandStore | None = None,
) -> str:
    """Insert a new command. ``trust`` overrides the default new-command
    trust (TRUST_NEW_COMMAND, normally 50). Useful for "I know this is
    a good command, start it higher" or "this came from a less-trusted
    source, start it lower".

    Supports parameterized commands with {{param}} placeholders in both
    the intent phrase and the command, e.g.:
        teach("show logs for {{container}}", "docker logs --tail 100 {{container}}")
    """
    store = store or CommandStore(chat_id=chat_id)
    return store.teach(intent_phrase, command, trust=trust)


def status(chat_id: str = "default", *, store: CommandStore | None = None) -> dict:
    store = store or CommandStore(chat_id=chat_id)
    return {"command_count": store.count(), "chat_id": chat_id}


def list_commands(
    chat_id: str = "default",
    *,
    limit: int = 20,
    offset: int = 0,
    min_trust: float = 0.0,
    store: CommandStore | None = None,
) -> dict:
    """List commands in the table, sorted by trust desc. Returns a dict
    with `commands` (list of dicts) and `total` (unfiltered count)."""
    store = store or CommandStore(chat_id=chat_id)
    rows = store.list_all(limit=limit, offset=offset, min_trust=min_trust)
    return {
        "chat_id": chat_id,
        "commands": rows,
        "limit": limit,
        "offset": offset,
        "total": store.count(),
    }
