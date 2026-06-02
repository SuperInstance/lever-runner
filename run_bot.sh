#!/usr/bin/env bash
# Run the Lever-Runner Telegram bot. Detached, logs to logs/bot.log.
set -e
cd "$(dirname "$0")"
mkdir -p logs
export PYTHONPATH="$PWD/src"
exec ./.venv/bin/python -m lever_runner.bot >> logs/bot.log 2>&1
