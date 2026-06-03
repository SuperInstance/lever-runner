"""
conftest.py — shared fixtures for lever-runner tests.

Provides mock Telegram objects (Update, Message, Context), fake
DoResult/Match/RunResult dataclasses, and auto-used environment
cleanup so tests don't pollute each other.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Mock Telegram objects
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_message() -> MagicMock:
    """A MagicMock that acts like telegram.Message."""
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.text = ""
    msg.chat.id = 123456789
    return msg


@pytest.fixture
def mock_update(mock_message: MagicMock) -> MagicMock:
    """A MagicMock that acts like telegram.Update."""
    upd = MagicMock()
    upd.effective_user.id = 123456789
    upd.effective_chat.id = 123456789
    upd.message = mock_message
    return upd


@pytest.fixture
def mock_context() -> MagicMock:
    """A MagicMock that acts like telegram.ext.CallbackContext.

    ctx.args holds list of command arguments (everything after /cmd).
    """
    ctx = MagicMock()
    ctx.args = []
    ctx.bot = MagicMock()
    return ctx


@pytest.fixture
def mock_unauthorized_update(mock_message: MagicMock) -> MagicMock:
    """An update from a user NOT on the allowlist."""
    upd = MagicMock()
    upd.effective_user.id = 999999999
    upd.effective_chat.id = 999999999
    upd.message = mock_message
    return upd


# ---------------------------------------------------------------------------
# Auto-used environment cleanup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env() -> None:
    """Reset env vars before each test so tests are hermetic.

    We patch the os.getenv calls that bot.py reads at import time
    by setting/clearing ALLOWED_USER_ID per test, and ensure the
    important env vars are clean.
    """
    import os

    # Save and restore
    saved = {}
    keys = [
        "ALLOWED_USER_ID",
        "TELEGRAM_BOT_TOKEN",
        "LLM_BACKEND",
        "LLM_API_KEY",
        "DEEPINFRA_API_KEY",
        "MINIMAX_API_KEY",
        "LLM_FALLBACKS",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "MATCH_SIMILARITY_FLOOR",
        "COMMAND_TIMEOUT_SEC",
    ]
    for k in keys:
        saved[k] = os.environ.pop(k, None)

    yield

    for k in keys:
        if saved[k] is not None:
            os.environ[k] = saved[k]
        else:
            os.environ.pop(k, None)
