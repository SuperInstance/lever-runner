#!/usr/bin/env bash
# Lever-Runner installer.
# Tested on Ubuntu 22.04 ARM (Oracle Cloud Free Tier).
# Idempotent. Re-running should be safe.

set -euo pipefail

REPO_DIR="${LEVER_RUNNER_DIR:-$HOME/lever-runner}"

echo "==> Lever-Runner installer"
echo "    target: $REPO_DIR"
echo

# 1. system deps
if command -v apt >/dev/null 2>&1; then
  echo "==> apt: ensuring python3, python3-venv, python3-pip, git, curl"
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates
else
  echo "!! apt not found; please install python3, venv, pip, git, curl manually"
fi

# 2. clone or update
if [ -d "$REPO_DIR/.git" ]; then
  echo "==> repo exists; pulling"
  git -C "$REPO_DIR" pull --ff-only
else
  echo "==> cloning SuperInstance/lever-runner"
  git clone https://github.com/SuperInstance/lever-runner.git "$REPO_DIR"
fi

# 3. venv + deps
cd "$REPO_DIR"
if [ ! -d .venv ]; then
  echo "==> creating venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> pip install"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 4. .env
if [ ! -f .env ]; then
  echo "==> creating .env from .env.example"
  cp .env.example .env
  echo "    *** edit .env to set TELEGRAM_BOT_TOKEN and (optionally) LLM_API_KEY ***"
fi

# 5. seed the database
echo "==> seeding LanceDB (this downloads the embedding model on first run)"
python init_db.py --reset

# 6. systemd (optional)
if command -v systemctl >/dev/null 2>&1; then
  echo "==> installing systemd unit"
  sudo cp systemd/lever-runner-bot.service /etc/systemd/system/lever-runner-bot.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now lever-runner-bot.service
  echo "    status:"
  sudo systemctl --no-pager status lever-runner-bot.service | sed 's/^/      /'
else
  echo "==> systemd not available; start the bot manually:"
  echo "      cd $REPO_DIR && source .venv/bin/activate && python -m lever_runner.bot"
fi

echo
echo "==> done."
echo "    Telegram: message your bot with /start"
echo "    CLI:      python -m lever_runner 'check disk usage'"
echo "    HTTP:     python -m lever_runner.http_api   (default :8765)"
echo "    bench:    python -m lever_runner.benchmark"
