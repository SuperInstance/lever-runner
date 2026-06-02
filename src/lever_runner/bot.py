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

from .orchestrator import do, status, teach

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("lever-runner.bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_ID = os.getenv("ALLOWED_USER_ID", "").strip()


HELP_TEXT = (
    "Lever-Runner — post-inference command executor.\n\n"
    "/do <request>             run a command from the pre-approved table\n"
    '/teach "phrase" | <cmd>  add a new command (trust starts at 50)\n'
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
    # /teach "intent phrase here" | shell command goes here
    raw = update.message.text.partition(" ")[2].strip()
    if "|" not in raw:
        await update.message.reply_text(
            'usage: /teach "intent phrase" | shell command\n'
            'example: /teach "show git status" | git status'
        )
        return
    phrase_part, _, cmd_part = raw.partition("|")
    phrase = phrase_part.strip().strip('"').strip("'")
    command = cmd_part.strip()
    if not phrase or not command:
        await update.message.reply_text("both intent phrase and command are required")
        return
    chat_id = str(update.effective_chat.id)
    row_id = teach(phrase, command, chat_id=chat_id)
    await update.message.reply_text(
        f"taught. id={row_id[:8]}\nphrase: {phrase!r}\ncommand: {command}"
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
    # Plain text (no /command) → treated as /do
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_fallback))
    log.info("polling Telegram…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
