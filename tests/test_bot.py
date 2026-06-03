"""
test_bot.py — Comprehensive pytest suite for lever-runner's Telegram bot adapter.

Strategy: import bot.py once at module level (which loads .env), then use
unittest.mock.patch.object to override module-level globals (ALLOWED_USER_ID,
TELEGRAM_BOT_TOKEN) and patch() to mock orchestrator functions per test.

All "authorized" tests patch ALLOWED_USER_ID to match the mock_update fixture
(123456789) because the real .env has a different user id.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure tests/ is on sys.path for module imports
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from helpers import FakeDoResult, FakeMatch, FakeRunResult

# One-time module import — loads .env, creates module-level globals.
# All subsequent tests use patch.object() to override globals as needed.
from src.lever_runner import bot as bot_mod  # noqa: E402

# The mock user id used in mock_update fixture
_MOCK_USER_ID = "123456789"


@contextmanager
def _authorized() -> Iterator[None]:
    """Context manager: patch ALLOWED_USER_ID to match mock_update."""
    with patch.object(bot_mod, "ALLOWED_USER_ID", _MOCK_USER_ID):
        yield


# ---------------------------------------------------------------------------
# Tests for _is_authorized
# ---------------------------------------------------------------------------


class TestAuthorization:
    """ALLOWED_USER_ID controls who can talk to the bot."""

    def test_authorized_when_allowlist_empty(self):
        """When ALLOWED_USER_ID is unset, everyone is authorized."""
        with patch.object(bot_mod, "ALLOWED_USER_ID", ""):
            msg = MagicMock()
            msg.effective_user.id = 12345
            assert bot_mod._is_authorized(msg) is True
            msg.effective_user.id = 0
            assert bot_mod._is_authorized(msg) is True
            msg.effective_user.id = -1
            assert bot_mod._is_authorized(msg) is True

    def test_authorized_when_allowlist_matches(self):
        """When ALLOWED_USER_ID is set and user id matches."""
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            msg = MagicMock()
            msg.effective_user.id = 42
            assert bot_mod._is_authorized(msg) is True

    def test_authorized_when_allowlist_does_not_match(self):
        """When ALLOWED_USER_ID is set and user id differs."""
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            msg = MagicMock()
            msg.effective_user.id = 999
            assert bot_mod._is_authorized(msg) is False

    def test_authorized_handles_none_user(self):
        """When effective_user is None (e.g. channel post), deny."""
        msg = MagicMock()
        msg.effective_user = None
        assert bot_mod._is_authorized(msg) is False

    def test_deny_sends_expected_message(self):
        """_deny sends the correct 'not authorized' reply."""
        msg = MagicMock()
        msg.message = MagicMock()
        msg.message.reply_text = AsyncMock()
        import asyncio

        asyncio.run(bot_mod._deny(msg))
        msg.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for _format_do
# ---------------------------------------------------------------------------


class TestFormatDo:
    """_format_do renders DoResult into a user-facing string."""

    def test_format_do_basic_success(self):
        result = FakeDoResult()
        output = bot_mod._format_do(result)
        assert "intent: 'test command'" in output
        assert "matched: 'test command'" in output
        assert "command: echo hello" in output
        assert "trust:   75.0" in output
        assert "succ 10 / fail 2" in output
        assert "exit:    0   (ok, 0.42s)" in output
        assert "hello world" in output

    def test_format_do_failed_command(self):
        result = FakeDoResult(
            ok=False,
            run=FakeRunResult(ok=False, exit_code=1, stdout="", stderr="error: not found"),
        )
        output = bot_mod._format_do(result)
        assert "exit:    1   (fail, 0.42s)" in output
        assert "error: not found" in output

    def test_format_do_no_match(self):
        result = FakeDoResult(
            match=None, run=None, no_match=True, error="(no matching command in the table)"
        )
        output = bot_mod._format_do(result)
        assert "(no matching command in the table)" in output

    def test_format_do_error_without_match(self):
        result = FakeDoResult(match=None, run=None, error="LLM returned an empty intent phrase")
        output = bot_mod._format_do(result)
        assert "error: LLM returned an empty intent phrase" in output

    def test_format_do_no_run(self):
        """When result.run is None, skip stdout/stderr section."""
        result = FakeDoResult(run=None)
        output = bot_mod._format_do(result)
        assert "intent:" in output
        assert "matched:" in output
        assert "exit:" not in output

    def test_format_do_stdout_truncation(self):
        """stdout > 3000 chars gets truncated."""
        long_out = "line\n" * 2000
        result = FakeDoResult(run=FakeRunResult(stdout=long_out))
        output = bot_mod._format_do(result)
        assert "…(truncated)" in output

    def test_format_do_stderr_truncation(self):
        """stderr > 1500 chars gets truncated."""
        long_err = "error\n" * 500
        result = FakeDoResult(
            ok=False,
            run=FakeRunResult(ok=False, exit_code=1, stdout="", stderr=long_err),
        )
        output = bot_mod._format_do(result)
        assert "…(truncated)" in output

    def test_format_do_empty_stdout_stderr(self):
        """No stdout/stderr sections when both are empty."""
        result = FakeDoResult(run=FakeRunResult(stdout="", stderr=""))
        output = bot_mod._format_do(result)
        assert "--- stdout ---" not in output
        assert "--- stderr ---" not in output


# ---------------------------------------------------------------------------
# Tests for /start
# ---------------------------------------------------------------------------


class TestCmdStart:
    """/start handler."""

    @pytest.mark.asyncio
    async def test_start_authorized(self, mock_update, mock_context):
        with _authorized():
            await bot_mod.cmd_start(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "Lever-Runner" in reply
        assert "/do" in reply
        assert "/teach" in reply

    @pytest.mark.asyncio
    async def test_start_unauthorized(self, mock_unauthorized_update, mock_context):
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_start(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for /help
# ---------------------------------------------------------------------------


class TestCmdHelp:
    @pytest.mark.asyncio
    async def test_help_authorized(self, mock_update, mock_context):
        with _authorized():
            await bot_mod.cmd_help(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "Lever-Runner" in reply

    @pytest.mark.asyncio
    async def test_help_unauthorized(self, mock_unauthorized_update, mock_context):
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_help(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for /status
# ---------------------------------------------------------------------------


class TestCmdStatus:
    @pytest.mark.asyncio
    async def test_status_authorized(self, mock_update, mock_context):
        mock_status = {"chat_id": "123456789", "command_count": 66}
        with _authorized(), patch("src.lever_runner.bot.status", return_value=mock_status):
            await bot_mod.cmd_status(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "commands in table: 66" in reply
        assert "123456789" in reply
        assert "trust floor for auto-run: 40" in reply
        assert "new commands start at trust 50" in reply

    @pytest.mark.asyncio
    async def test_status_authorized_zero_commands(self, mock_update, mock_context):
        mock_status = {"chat_id": "123456789", "command_count": 0}
        with _authorized(), patch("src.lever_runner.bot.status", return_value=mock_status):
            await bot_mod.cmd_status(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        assert "commands in table: 0" in mock_update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_status_unauthorized(self, mock_unauthorized_update, mock_context):
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_status(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for /commands
# ---------------------------------------------------------------------------


class TestCmdCommands:
    @pytest.mark.asyncio
    async def test_commands_authorized_empty(self, mock_update, mock_context):
        mock_listing = {"chat_id": "123456789", "commands": [], "total": 0}
        with _authorized(), patch("src.lever_runner.bot.list_commands", return_value=mock_listing):
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "page 1 of 0" in reply
        assert "empty" in reply

    @pytest.mark.asyncio
    async def test_commands_authorized_with_results(self, mock_update, mock_context):
        mock_listing = {
            "chat_id": "123456789",
            "commands": [
                {
                    "intent_phrase": "show disk usage",
                    "trust_score": 90.0,
                    "success_count": 15,
                    "failure_count": 1,
                    "last_run": "2026-06-01T",
                },
                {
                    "intent_phrase": "list files",
                    "trust_score": 50.0,
                    "success_count": 3,
                    "failure_count": 0,
                    "last_run": "",
                },
            ],
            "total": 2,
        }
        with _authorized(), patch("src.lever_runner.bot.list_commands", return_value=mock_listing):
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "page 1/1" in reply
        assert "show disk usage" in reply
        assert "list files" in reply
        assert "90.0" in reply

    @pytest.mark.asyncio
    async def test_commands_with_limit(self, mock_update, mock_context):
        mock_context.args = ["50"]
        mock_listing = {"chat_id": "123456789", "commands": [], "total": 0}
        with _authorized(), patch("src.lever_runner.bot.list_commands", return_value=mock_listing) as mock_lc:
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_lc.assert_called_once()
        kwargs = mock_lc.call_args.kwargs
        assert kwargs.get("limit") == 50

    @pytest.mark.asyncio
    async def test_commands_with_page(self, mock_update, mock_context):
        mock_context.args = ["20", "--page=2"]
        mock_listing = {"chat_id": "123456789", "commands": [], "total": 25}
        with _authorized(), patch("src.lever_runner.bot.list_commands", return_value=mock_listing):
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "page 2 of 2" or "page 2/2" in reply

    @pytest.mark.asyncio
    async def test_commands_limit_clamped(self, mock_update, mock_context):
        mock_context.args = ["500"]  # should clamp to 100
        mock_listing = {"chat_id": "123456789", "commands": [], "total": 0}
        with _authorized(), patch("src.lever_runner.bot.list_commands", return_value=mock_listing) as mock_lc:
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_lc.assert_called_once()
        assert mock_lc.call_args.kwargs.get("limit") == 100

    @pytest.mark.asyncio
    async def test_commands_invalid_limit(self, mock_update, mock_context):
        mock_context.args = ["notanumber"]
        with _authorized(), patch("src.lever_runner.bot.list_commands") as mock_lc:
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "usage: /commands [N] [--page=K]"
        )
        mock_lc.assert_not_called()

    @pytest.mark.asyncio
    async def test_commands_invalid_page(self, mock_update, mock_context):
        mock_context.args = ["10", "--page=abc"]
        with _authorized(), patch("src.lever_runner.bot.list_commands") as mock_lc:
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "--page= expects a number"
        )
        mock_lc.assert_not_called()

    @pytest.mark.asyncio
    async def test_commands_unauthorized(self, mock_unauthorized_update, mock_context):
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_commands(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for /do
# ---------------------------------------------------------------------------


class TestCmdDo:
    @pytest.mark.asyncio
    async def test_do_basic(self, mock_update, mock_context):
        mock_context.args = ["show", "disk", "usage"]
        mock_result = FakeDoResult()
        with _authorized(), patch("src.lever_runner.bot.do", return_value=mock_result):
            await bot_mod.cmd_do(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "intent:" in reply

    @pytest.mark.asyncio
    async def test_do_success_output(self, mock_update, mock_context):
        mock_context.args = ["check", "memory"]
        mock_result = FakeDoResult(
            intent="check memory usage",
            match=FakeMatch(intent_phrase="check memory usage", command="free -h"),
            run=FakeRunResult(exit_code=0, stdout="Mem: 8.1G total, 3.2G used", stderr=""),
        )
        with _authorized(), patch("src.lever_runner.bot.do", return_value=mock_result):
            await bot_mod.cmd_do(mock_update, mock_context)
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "check memory usage" in reply
        assert "free -h" in reply
        assert "Mem: 8.1G total" in reply

    @pytest.mark.asyncio
    async def test_do_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with _authorized(), patch("src.lever_runner.bot.do") as mock_do:
            await bot_mod.cmd_do(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "usage: /do <your request>"
        )
        mock_do.assert_not_called()

    @pytest.mark.asyncio
    async def test_do_no_match(self, mock_update, mock_context):
        mock_context.args = ["show", "disk"]
        mock_result = FakeDoResult(
            ok=False, match=None, no_match=True,
            error="no commands in the table yet",
        )
        with _authorized(), patch("src.lever_runner.bot.do", return_value=mock_result):
            await bot_mod.cmd_do(mock_update, mock_context)
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "(no matching command in the table)" in reply

    @pytest.mark.asyncio
    async def test_do_unauthorized(self, mock_unauthorized_update, mock_context):
        mock_context.args = ["show", "disk"]
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_do(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for /teach
# ---------------------------------------------------------------------------


class TestCmdTeach:
    @pytest.mark.asyncio
    async def test_teach_basic(self, mock_update, mock_context):
        mock_update.message.text = '/teach "check disk" | df -h'
        with _authorized(), patch("src.lever_runner.bot.teach", return_value="row_id_12345678"):
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "taught" in reply
        assert "row_id_1234" in reply  # bot truncates to 8 chars
        assert "check disk" in reply
        assert "df -h" in reply

    @pytest.mark.asyncio
    async def test_teach_with_trust_flag(self, mock_update, mock_context):
        mock_update.message.text = '/teach --trust=90 "restart nginx" | sudo systemctl restart nginx'
        with _authorized(), patch("src.lever_runner.bot.teach", return_value="row_abc") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_teach.assert_called_once()
        _, kwargs = mock_teach.call_args
        assert kwargs.get("trust") == 90.0

    @pytest.mark.asyncio
    async def test_teach_with_trust_flag_separate_value(self, mock_update, mock_context):
        """/teach --trust 70 "phrase" | command"""
        mock_update.message.text = '/teach --trust 70 "reboot server" | sudo reboot'
        with _authorized(), patch("src.lever_runner.bot.teach", return_value="row_def") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_teach.assert_called_once()
        _, kwargs = mock_teach.call_args
        assert kwargs.get("trust") == 70.0

    @pytest.mark.asyncio
    async def test_teach_missing_pipe(self, mock_update, mock_context):
        mock_update.message.text = '/teach "check disk" df -h'
        with _authorized(), patch("src.lever_runner.bot.teach") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "usage: /teach" in reply.replace("'", "")
        mock_teach.assert_not_called()

    @pytest.mark.asyncio
    async def test_teach_missing_phrase(self, mock_update, mock_context):
        mock_update.message.text = '/teach " " | ls'
        with _authorized(), patch("src.lever_runner.bot.teach") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "both intent phrase and command" in reply
        mock_teach.assert_not_called()

    @pytest.mark.asyncio
    async def test_teach_invalid_trust_value(self, mock_update, mock_context):
        """--trust=N where N is outside 0-100."""
        mock_update.message.text = '/teach --trust=150 "test" | echo ok'
        with _authorized(), patch("src.lever_runner.bot.teach") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "--trust must be a number 0-100"
        )
        mock_teach.assert_not_called()

    @pytest.mark.asyncio
    async def test_teach_invalid_trust_string(self, mock_update, mock_context):
        """--trust=N where N is not a number."""
        mock_update.message.text = '/teach --trust=abc "test" | echo ok'
        with _authorized(), patch("src.lever_runner.bot.teach") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "--trust must be a number 0-100"
        )
        mock_teach.assert_not_called()

    @pytest.mark.asyncio
    async def test_teach_unknown_flag(self, mock_update, mock_context):
        mock_update.message.text = '/teach --foo "test" | echo ok'
        with _authorized(), patch("src.lever_runner.bot.teach") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        assert "unknown flag: --foo" in mock_update.message.reply_text.call_args[0][0]
        mock_teach.assert_not_called()

    @pytest.mark.asyncio
    async def test_teach_trust_missing_value(self, mock_update, mock_context):
        """--trust without a value in separate form."""
        mock_update.message.text = "/teach --trust"
        with _authorized(), patch("src.lever_runner.bot.teach") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "--trust requires a value"
        )
        mock_teach.assert_not_called()

    @pytest.mark.asyncio
    async def test_teach_unauthorized(self, mock_unauthorized_update, mock_context):
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_teach(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for /stats
# ---------------------------------------------------------------------------


class TestCmdStats:
    @pytest.mark.asyncio
    async def test_stats_matched(self, mock_update, mock_context):
        mock_context.args = ["show", "disk", "usage"]
        with (
            _authorized(),
            patch("src.lever_runner.store.CommandStore") as MockStore,
            patch.dict(os.environ, {"MATCH_SIMILARITY_FLOOR": "0.55"}),
        ):
            mock_store = MockStore.return_value
            mock_match = MagicMock()
            mock_match.id = "abc123"
            mock_match.intent_phrase = "show disk usage"
            mock_match.command = "df -h"
            mock_match.trust_score = 85.0
            mock_match.success_count = 20
            mock_match.failure_count = 1
            mock_match.score = 0.1
            mock_match.similarity = 0.9
            mock_store.find_best.return_value = [mock_match]
            mock_store.get_by_id.return_value = {
                "last_run": "2026-06-01T12:00:00",
                "last_result": "ok",
                "created_at": "2026-01-15T10:00:00",
            }
            await bot_mod.cmd_stats(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "show disk usage" in reply
        assert "df -h" in reply
        assert "trust: 85.0" in reply
        assert "success: 20" in reply

    @pytest.mark.asyncio
    async def test_stats_no_args(self, mock_update, mock_context):
        mock_context.args = []
        with _authorized(), patch("src.lever_runner.store.CommandStore") as MockStore:
            await bot_mod.cmd_stats(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once_with(
            "usage: /stats <phrase>"
        )
        MockStore.assert_not_called()

    @pytest.mark.asyncio
    async def test_stats_no_match(self, mock_update, mock_context):
        mock_context.args = ["nonexistent", "command"]
        with (
            _authorized(),
            patch("src.lever_runner.store.CommandStore") as MockStore,
            patch.dict(os.environ, {"MATCH_SIMILARITY_FLOOR": "0.55"}),
        ):
            mock_store = MockStore.return_value
            mock_match = MagicMock()
            mock_match.id = "abc"
            mock_match.similarity = 0.3
            mock_store.find_best.return_value = [mock_match]
            await bot_mod.cmd_stats(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "no match" in reply
        assert "similarity: 0.300" in reply

    @pytest.mark.asyncio
    async def test_stats_unauthorized(self, mock_unauthorized_update, mock_context):
        mock_context.args = ["show", "disk"]
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_stats(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for fallback (plain text → /do)
# ---------------------------------------------------------------------------


class TestCmdFallback:
    @pytest.mark.asyncio
    async def test_fallback_authorized(self, mock_update, mock_context):
        mock_update.message.text = "check disk usage"
        mock_result = FakeDoResult()
        with _authorized(), patch("src.lever_runner.bot.do", return_value=mock_result):
            await bot_mod.cmd_fallback(mock_update, mock_context)
        mock_update.message.reply_text.assert_awaited_once()
        reply = mock_update.message.reply_text.call_args[0][0]
        assert "intent:" in reply

    @pytest.mark.asyncio
    async def test_fallback_unauthorized(self, mock_unauthorized_update, mock_context):
        mock_unauthorized_update.message.text = "check disk"
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await bot_mod.cmd_fallback(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )


# ---------------------------------------------------------------------------
# Tests for main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_raises_without_token(self):
        """main() raises SystemExit when TELEGRAM_BOT_TOKEN is empty."""
        with (
            patch.object(bot_mod, "TELEGRAM_BOT_TOKEN", ""),
            patch("src.lever_runner.bot.log"),
            pytest.raises(SystemExit),
        ):
            bot_mod.main()

    def test_main_starts_with_token(self):
        """main() builds the Application and returns 0."""
        mock_app = MagicMock()
        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with (
            patch.object(bot_mod, "TELEGRAM_BOT_TOKEN", "fake:token"),
            patch.object(Application, "builder", return_value=mock_builder),
            patch.object(bot_mod, "log"),
            patch.object(mock_app, "run_polling"),
        ):
            rc = bot_mod.main()

        assert rc == 0
        mock_builder.token.assert_called_once_with("fake:token")
        mock_builder.build.assert_called_once()

    def test_main_registers_handlers(self):
        """main() registers 8 handlers via add_handler."""
        mock_app = MagicMock()
        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = mock_app

        with (
            patch.object(bot_mod, "TELEGRAM_BOT_TOKEN", "fake:token"),
            patch.object(Application, "builder", return_value=mock_builder),
            patch.object(bot_mod, "log"),
            patch.object(mock_app, "run_polling"),
        ):
            bot_mod.main()

        assert mock_app.add_handler.call_count == 8


# ---------------------------------------------------------------------------
# Integration-style tests: orchestrator call args
# ---------------------------------------------------------------------------


class TestOrchestratorIntegration:
    """Handlers call orchestrator functions with the right args."""

    @pytest.mark.asyncio
    async def test_do_passes_combined_args(self, mock_update, mock_context):
        mock_context.args = ["check", "disk", "usage"]
        mock_result = FakeDoResult()
        with _authorized(), patch("src.lever_runner.bot.do", return_value=mock_result) as mock_do:
            await bot_mod.cmd_do(mock_update, mock_context)
        mock_do.assert_called_once_with(
            "check disk usage",
            source="123456789",
            chat_id="123456789",
        )

    @pytest.mark.asyncio
    async def test_teach_passes_chat_id(self, mock_update, mock_context):
        mock_update.message.text = '/teach "show date" | date'
        mock_update.effective_chat.id = 42
        with _authorized(), patch("src.lever_runner.bot.teach", return_value="row") as mock_teach:
            await bot_mod.cmd_teach(mock_update, mock_context)
        mock_teach.assert_called_once_with(
            "show date", "date",
            chat_id="42",
            trust=None,
        )

    @pytest.mark.asyncio
    async def test_status_passes_chat_id(self, mock_update, mock_context):
        mock_update.effective_chat.id = 77
        with _authorized(), patch("src.lever_runner.bot.status",
                                  return_value={"chat_id": "77", "command_count": 5}) as mock_status:
            await bot_mod.cmd_status(mock_update, mock_context)
        mock_status.assert_called_once_with(chat_id="77")

    @pytest.mark.asyncio
    async def test_commands_passes_chat_id_and_limit(self, mock_update, mock_context):
        mock_context.args = ["30", "--page=3"]
        mock_update.effective_chat.id = 99
        mock_listing = {"chat_id": "99", "commands": [], "total": 100}
        with _authorized(), patch("src.lever_runner.bot.list_commands", return_value=mock_listing) as mock_lc:
            await bot_mod.cmd_commands(mock_update, mock_context)
        mock_lc.assert_called_once_with(
            chat_id="99", limit=30, offset=60
        )

    @pytest.mark.asyncio
    async def test_fallback_passes_text_and_chat_id(self, mock_update, mock_context):
        mock_update.message.text = "  hello world  "
        mock_update.effective_chat.id = 55
        mock_result = FakeDoResult()
        with _authorized(), patch("src.lever_runner.bot.do", return_value=mock_result) as mock_do:
            await bot_mod.cmd_fallback(mock_update, mock_context)
        mock_do.assert_called_once_with(
            "hello world",
            source="55",
            chat_id="55",
        )

    @pytest.mark.asyncio
    async def test_do_empty_args_returns_usage(self, mock_update, mock_context):
        """When args are empty, show usage and don't call do()."""
        mock_context.args = []
        with _authorized(), patch("src.lever_runner.bot.do") as mock_do:
            await bot_mod.cmd_do(mock_update, mock_context)
        mock_do.assert_not_called()
        mock_update.message.reply_text.assert_awaited_once_with(
            "usage: /do <your request>"
        )


# ---------------------------------------------------------------------------
# Tests for error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Exceptions from orchestrator propagate through handlers."""

    @pytest.mark.asyncio
    async def test_orchestrator_do_raises(self, mock_update, mock_context):
        mock_context.args = ["crash", "test"]
        with _authorized(), patch("src.lever_runner.bot.do", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                await bot_mod.cmd_do(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_orchestrator_status_raises(self, mock_update, mock_context):
        with _authorized(), patch("src.lever_runner.bot.status", side_effect=RuntimeError("db down")):
            with pytest.raises(RuntimeError, match="db down"):
                await bot_mod.cmd_status(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_orchestrator_teach_raises(self, mock_update, mock_context):
        mock_update.message.text = '/teach "test" | echo ok'
        with _authorized(), patch("src.lever_runner.bot.teach", side_effect=RuntimeError("db error")):
            with pytest.raises(RuntimeError, match="db error"):
                await bot_mod.cmd_teach(mock_update, mock_context)


# ---------------------------------------------------------------------------
# /healthz raw endpoint (http_api.py logic)
# ---------------------------------------------------------------------------


class TestHealthz:
    """Validate /healthz response shapes from http_api.py."""

    def test_healthz_success_shape(self):
        from src.lever_runner.__init__ import __version__

        payload = {
            "ok": True,
            "version": __version__,
            "uptime_sec": 3600.0,
            "tables": {"commands_default": 70},
            "total_commands": 70,
        }
        assert payload["ok"] is True
        assert isinstance(payload["version"], str)
        assert payload["total_commands"] == 70

    def test_healthz_failure_shape(self):
        payload = {
            "ok": False,
            "version": "0.3.1",
            "uptime_sec": 42.0,
            "error": "lancedb unavailable: Connection refused",
        }
        assert payload["ok"] is False
        assert "Connection refused" in payload["error"]


# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------


class TestTokenBudget:
    """Token accounting on DoResult."""

    def test_do_result_has_token_counts(self):
        result = FakeDoResult(tokens_in=100, tokens_out=25)
        assert result.tokens_in == 100
        assert result.tokens_out == 25
        assert result.total_tokens == 125


# ---------------------------------------------------------------------------
# Allowlist comprehensive (parameterized over all handlers)
# ---------------------------------------------------------------------------


class TestAllowlistBehavior:
    """Every handler rejects unauthorized users."""

    COMMANDS = [
        "cmd_start", "cmd_help", "cmd_status", "cmd_do", "cmd_teach",
        "cmd_commands", "cmd_stats", "cmd_fallback",
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handler_name", COMMANDS)
    async def test_all_handlers_deny_unauthorized(self, mock_unauthorized_update, mock_context, handler_name):
        mock_unauthorized_update.message.text = '/teach "test" | echo ok'
        mock_context.args = ["test"]
        mock_unauthorized_update.message.reply_text = AsyncMock()
        handler = getattr(bot_mod, handler_name)
        with patch.object(bot_mod, "ALLOWED_USER_ID", "42"):
            await handler(mock_unauthorized_update, mock_context)
        mock_unauthorized_update.message.reply_text.assert_awaited_once_with(
            "not authorized. this bot is locked to a specific Telegram user."
        )
