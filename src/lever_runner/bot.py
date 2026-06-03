"""
bot.py — Telegram adapter for the orchestrator.

Run with:
    python -m lever_runner.bot

Handlers:
    /do <free text>            → run a command
    /teach "phrase" | <cmd>    → insert a new command at trust 50
    /status                    → table size + recent stats
    /start, /help              → usage

We deliberately do NOT use parse_mode=Markdown: the orchestrator returns
arbitrary command output (filesystem paths, error lines, escape codes),
and any user-controlled text inside Markdown triggers Telegram client
crashes on bad syntax. Plain text is the right call.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .orchestrator import do, list_commands, status, teach

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lever-runner.bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "").strip()


HELP_TEXT = (
    "Lever-Runner — post-inference command executor.\n\n"
    "/do <request>             run a command from the pre-approved table\n"
    '/teach "phrase" | <cmd>  add a new command (trust starts at 50)\n'
    "/teach --trust=N ...      override starting trust (0-100)\n"
    "/commands [N] [--page=K]  list commands in this chat, sorted by trust\n"
    "/stats <phrase>           show full stats for one command\n"
    "/status                   show how many commands are loaded\n\n"
    "The LLM only sees your request as a short phrase. It never invents a command."
)


def _format_do(result) -> str:
    lines = []
    lines.append(f"intent: {result.intent!r}")
    if result.no_match:
        lines.append("(no matching command in the table)")
        return "\n".join(lines)
    if result.error and result.match is None:
        lines.append(f"error: {result.error}")
        return "\n".join(lines)
    m = result.match
    lines.append(f"matched: {m.intent_phrase!r}")
    lines.append(f"command: {m.command}")
    lines.append(f"trust:   {m.trust_score:.1f}  (succ {m.success_count} / fail {m.failure_count})")
    if result.run is None:
        return "\n".join(lines)
    r = result.run
    lines.append(f"exit:    {r.exit_code}   ({'ok' if r.ok else 'fail'}, {r.duration_sec:.2f}s)")
    if r.stdout.strip():
        out = r.stdout.strip()
        if len(out) > 3000:
            out = out[:3000] + "\n…(truncated)"
        lines.append("--- stdout ---\n" + out)
    if r.stderr.strip():
        err = r.stderr.strip()
        if len(err) > 1500:
            err = err[:1500] + "\n…(truncated)"
        lines.append("--- stderr ---\n" + err)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


def _is_authorized(update: Update) -> bool:
    """True if the message is from the allowed user (or no allowlist set).

    When ALLOWED_USER_ID is unset, the bot responds to anyone — useful for
    testing. Set it in .env to a Telegram numeric user ID to lock down.
    """
    if update.effective_user is None:
        return False
    if not ALLOWED_USER_ID:
        return True
    try:
        return str(update.effective_user.id) == str(ALLOWED_USER_ID)
    except (AttributeError, TypeError):
        return False


async def _deny(update: Update) -> None:
    await update.message.reply_text(
        "not authorized. this bot is locked to a specific Telegram user."
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return
    chat_id = str(update.effective_chat.id)
    s = status(chat_id=chat_id)
    await update.message.reply_text(
        f"chat: {s['chat_id']}\n"
        f"commands in table: {s['command_count']}\n"
        f"trust floor for auto-run: 40\n"
        f"new commands start at trust 50"
    )


async def cmd_commands(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """List commands in the table, sorted by trust desc. Paginated.

    Usage:
        /commands             first 20 (default)
        /commands 50          first 50
        /commands 20 --page=2  page 2 of size 20
    """
    if not _is_authorized(update):
        await _deny(update)
        return
    chat_id = str(update.effective_chat.id)
    # Parse: first arg is limit, then optional --page=N
    limit = 20
    page = 1
    args = list(ctx.args or [])
    if args and not args[0].startswith("--"):
        try:
            limit = int(args[0])
            limit = max(1, min(limit, 100))
        except ValueError:
            await update.message.reply_text("usage: /commands [N] [--page=K]")
            return
        args = args[1:]
    for a in args:
        if a.startswith("--page="):
            try:
                page = max(1, int(a.split("=", 1)[1]))
            except ValueError:
                await update.message.reply_text("--page= expects a number")
                return
    offset = (page - 1) * limit
    listing = list_commands(chat_id=chat_id, limit=limit, offset=offset)
    total = listing["total"]
    rows = listing["commands"]
    if not rows:
        await update.message.reply_text(
            f"chat: {chat_id}\npage {page} of {(total + limit - 1) // limit}: empty"
        )
        return
    lines = [f"chat: {chat_id}  page {page}/{(total + limit - 1) // limit}  ({total} total)"]
    for r in rows:
        phrase = str(r.get("intent_phrase", ""))[:40]
        trust = float(r.get("trust_score", 0.0))
        succ = int(r.get("success_count", 0))
        fail = int(r.get("failure_count", 0))
        last_run = r.get("last_run", "")
        last = f"  last: {last_run[:10]}" if last_run else ""
        lines.append(
            f"  {trust:5.1f}  {succ:>3}/{fail:<3}  {phrase}{last}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Show full stats for a specific command, looked up by phrase.

    Usage:
        /stats show disk usage
    """
    if not _is_authorized(update):
        await _deny(update)
        return
    if not ctx.args:
        await update.message.reply_text("usage: /stats <phrase>")
        return
    import os
    from .store import CommandStore
    phrase = " ".join(ctx.args)
    chat_id = str(update.effective_chat.id)
    sm = CommandStore(chat_id=chat_id)
    matches = sm.find_best(phrase, top_k=1)
    sim_floor = float(os.getenv("MATCH_SIMILARITY_FLOOR", "0.55"))
    if not matches or matches[0].similarity < sim_floor:
        await update.message.reply_text(
            f"no match for {phrase!r} (top similarity: "
            f"{matches[0].similarity:.3f}, floor: {sim_floor:.2f})"
        )
        return
    m = matches[0]
    row = sm.get_by_id(m.id) or {}
    last_run = row.get("last_run", "")
    last_result = row.get("last_result", "")
    created = row.get("created_at", "")
    lines = [
        f"phrase: {m.intent_phrase!r}",
        f"command: {m.command}",
        f"trust: {m.trust_score:.1f}",
        f"success: {m.success_count}  failure: {m.failure_count}",
        f"created: {created[:19] if created else 'unknown'}",
        f"last run: {last_run[:19] if last_run else 'never'}  ({last_result or '—'})",
        f"distance: {m.score:.3f}  similarity: {m.similarity:.3f}",
        f"id: {m.id[:8]}",
    ]
    await update.message.reply_text("\n".join(lines))


async def cmd_do(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return
    if not ctx.args:
        await update.message.reply_text("usage: /do <your request>")
        return
    request = " ".join(ctx.args)
    chat_id = str(update.effective_chat.id)
    result = do(request, source=chat_id, chat_id=chat_id)
    await update.message.reply_text(_format_do(result))


async def cmd_teach(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        await _deny(update)
        return
    # /teach [--trust=N] "intent phrase here" | shell command goes here
    raw = update.message.text.partition(" ")[2].strip()
    # Parse optional leading flags (--trust=70, --trust 70).
    trust: float | None = None
    while raw.startswith("--"):
        flag, _, rest = raw.partition(" ")
        if flag.startswith("--trust="):
            try:
                trust = float(flag.split("=", 1)[1])
                if not 0 <= trust <= 100:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("--trust must be a number 0-100")
                return
            raw = rest.strip()
        elif flag.startswith("--trust"):
            # /teach --trust 70 "phrase" | cmd
            parts = rest.split(maxsplit=1)
            if not parts:
                await update.message.reply_text("--trust requires a value")
                return
            try:
                trust = float(parts[0])
                if not 0 <= trust <= 100:
                    raise ValueError
            except ValueError:
                await update.message.reply_text("--trust must be a number 0-100")
                return
            raw = parts[1].strip() if len(parts) > 1 else ""
        else:
            await update.message.reply_text(f"unknown flag: {flag}")
            return
    if "|" not in raw:
        await update.message.reply_text(
            'usage: /teach [--trust=N] "intent phrase" | shell command\n'
            'example: /teach "show git status" | git status\n'
            'example: /teach --trust=70 "show openclaw version" | openclaw --version'
        )
        return
    phrase_part, _, cmd_part = raw.partition("|")
    phrase = phrase_part.strip().strip('"').strip("'").strip()
    command = cmd_part.strip()
    if not phrase or not command:
        await update.message.reply_text("both intent phrase and command are required")
        return
    chat_id = str(update.effective_chat.id)
    row_id = teach(phrase, command, chat_id=chat_id, trust=trust)
    trust_msg = f" (trust={trust:.0f})" if trust is not None else ""
    await update.message.reply_text(
        f"taught{trust_msg}. id={row_id[:8]}\nphrase: {phrase!r}\ncommand: {command}"
    )


async def cmd_fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain text (no slash command) is treated as /do."""
    if not _is_authorized(update):
        await _deny(update)
        return
    text = update.message.text.strip()
    chat_id = str(update.effective_chat.id)
    result = do(text, source=chat_id, chat_id=chat_id)
    await update.message.reply_text(_format_do(result))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN is empty. Set it in .env first.")
    log.info("starting Lever-Runner bot")
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("do", cmd_do))
    app.add_handler(CommandHandler("teach", cmd_teach))
    app.add_handler(CommandHandler("commands", cmd_commands))
    app.add_handler(CommandHandler("stats", cmd_stats))
    # Plain text (no /command) → treated as /do
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_fallback))
    log.info("polling Telegram…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
