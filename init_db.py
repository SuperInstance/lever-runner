"""
init_db.py — Create the LanceDB `commands` table and seed it with 50 common
shell commands + their embeddings.

Run from the repo root:
    python init_db.py            # create + seed
    python init_db.py --reset    # drop existing table and rebuild

Schema (one row per pre-approved command):
    id             : str        # uuid4
    intent_phrase  : str        # the canonical human-language phrase
    command        : str        # the shell command to execute
    trust_score    : float      # 0..100
    success_count  : int
    failure_count  : int
    embedding      : list[float] (384 dims for all-MiniLM-L6-v2)

The embedding model is loaded lazily; this script is safe to re-run.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import List, Dict, Any

import lancedb
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

load_dotenv()

LANCEDB_PATH = os.getenv("LANCEDB_PATH", "./data/lever.lancedb")
LANCEDB_TABLE = os.getenv("LANCEDB_TABLE", "commands")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TRUST_NEW = float(os.getenv("TRUST_NEW_COMMAND", "50"))

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


# ---------------------------------------------------------------------------
# Seed pack: 50 common commands across git, docker, npm, system, networking,
# python, and devops. Intent phrases are written the way a real user would
# type them, so cosine similarity works well out of the box.
# ---------------------------------------------------------------------------

SEED_COMMANDS: List[Dict[str, str]] = [
    # --- system health ------------------------------------------------------
    {"intent": "show disk usage",                          "command": "df -h"},
    {"intent": "show memory usage",                        "command": "free -h"},
    {"intent": "show cpu info",                            "command": "lscpu"},
    {"intent": "show running processes",                    "command": "ps aux --sort=-%cpu | head -20"},
    {"intent": "show system uptime and load",              "command": "uptime"},
    {"intent": "show logged in users",                     "command": "who"},
    {"intent": "show kernel and hostname",                 "command": "uname -a && hostname"},
    {"intent": "show ip addresses",                        "command": "ip -4 addr show | grep inet"},
    {"intent": "show open ports",                          "command": "ss -tulnp"},
    {"intent": "show environment variables",               "command": "env | sort"},

    # --- git ---------------------------------------------------------------
    {"intent": "git status",                               "command": "git status"},
    {"intent": "git log oneline last ten commits",         "command": "git log --oneline -n 10"},
    {"intent": "git show current branch",                  "command": "git branch --show-current"},
    {"intent": "git list all branches",                    "command": "git branch -a"},
    {"intent": "git diff unstaged",                        "command": "git diff"},
    {"intent": "git fetch from origin",                    "command": "git fetch origin"},
    {"intent": "git pull from origin",                     "command": "git pull --ff-only"},
    {"intent": "git add everything and commit with message","command": "git add -A && git commit -m \"${MSG:-update}\""},

    # --- docker ------------------------------------------------------------
    {"intent": "show running docker containers",           "command": "docker ps"},
    {"intent": "show all docker containers",               "command": "docker ps -a"},
    {"intent": "show docker images",                       "command": "docker images"},
    {"intent": "show docker disk usage",                   "command": "docker system df"},
    {"intent": "show docker compose logs",                 "command": "docker compose logs --tail=100"},
    {"intent": "docker prune unused images",               "command": "docker image prune -af"},

    # --- python / pip ------------------------------------------------------
    {"intent": "show python version",                      "command": "python3 --version"},
    {"intent": "show pip version",                         "command": "pip --version"},
    {"intent": "list installed pip packages",              "command": "pip list"},
    {"intent": "show current pip package",                 "command": "pip show"},
    {"intent": "create a python venv",                     "command": "python3 -m venv .venv"},

    # --- npm / node --------------------------------------------------------
    {"intent": "show node version",                        "command": "node --version"},
    {"intent": "show npm version",                         "command": "npm --version"},
    {"intent": "list global npm packages",                 "command": "npm list -g --depth=0"},
    {"intent": "npm security audit for vulnerabilities",   "command": "npm audit --omit=dev"},

    # --- networking --------------------------------------------------------
    {"intent": "ping a host",                              "command": "ping -c 4 1.1.1.1"},
    {"intent": "show public ip",                           "command": "curl -s https://ifconfig.me"},
    {"intent": "show dns records for a domain",            "command": "dig +short"},
    {"intent": "trace route to a host",                    "command": "traceroute -m 15 1.1.1.1"},

    # --- files / disk ------------------------------------------------------
    {"intent": "show current directory and contents",      "command": "pwd && ls -la"},
    {"intent": "show size of current directory",           "command": "du -sh ."},
    {"intent": "find files modified in the last day",      "command": "find . -type f -mtime -1"},
    {"intent": "show disk usage by directory",             "command": "du -h --max-depth=1 . | sort -hr"},

    # --- services / systemd ------------------------------------------------
    {"intent": "list running systemd services",            "command": "systemctl list-units --type=service --state=running"},
    {"intent": "show status of a systemd service",         "command": "systemctl status"},
    {"intent": "show failed systemd services",             "command": "systemctl --failed"},
    {"intent": "show journal logs since today",            "command": "journalctl --since today --no-pager"},

    # --- ollama / ml -------------------------------------------------------
    {"intent": "list ollama models",                       "command": "ollama list"},
    {"intent": "show ollama version",                      "command": "ollama --version"},
    {"intent": "show running ollama models",               "command": "curl -s http://localhost:11434/api/ps"},
    {"intent": "show ollama logs",                         "command": "journalctl -u ollama --since today --no-pager"},

    # --- openclaw (this host runs it as a gateway on :18789) ---------------
    {"intent": "show openclaw version",                    "command": "openclaw --version"},
    {"intent": "show openclaw gateway status",             "command": "systemctl status openclaw --no-pager 2>/dev/null || pgrep -af openclaw"},
    {"intent": "tail openclaw logs",                       "command": "journalctl -u openclaw --since today --no-pager 2>/dev/null || tail -n 50 /home/linuxbrew/.linuxbrew/var/log/openclaw/*.log 2>/dev/null || echo 'no openclaw logs found'"},
    {"intent": "show openclaw config path",                "command": "ls -la /home/linuxbrew/.linuxbrew/etc/openclaw/ 2>/dev/null || echo 'no openclaw config dir'"},

    # --- lever-runner self-ops (so it can manage itself) -------------------
    {"intent": "show lever-runner version",                "command": "cd ~/lever-runner && .venv/bin/python -c 'from src.lever_runner import __version__; print(__version__)'"},
    {"intent": "show lever-runner git log",                "command": "cd ~/lever-runner && git log --oneline -n 10"},
    {"intent": "show lever-runner git status",             "command": "cd ~/lever-runner && git status"},
    {"intent": "run lever-runner benchmark",               "command": "cd ~/lever-runner && .venv/bin/python -m src.lever_runner.benchmark"},
    {"intent": "show lever-runner command count",          "command": "cd ~/lever-runner && .venv/bin/python -c 'from src.lever_runner.store import CommandStore; print(CommandStore().count(), \"commands\")'"},
    {"intent": "tail lever-runner token log",              "command": "tail -n 20 ~/lever-runner/logs/token_usage.jsonl 2>/dev/null || echo 'no token log yet'"},
    {"intent": "reseed lever-runner database",             "command": "cd ~/lever-runner && .venv/bin/python init_db.py --reset"},
    {"intent": "show lever-runner sandbox contents",       "command": "ls -la /tmp/lever-runner/ 2>/dev/null | head -20 || echo 'no sandbox yet'"},

    # --- this host (Oracle ARM, Ubuntu 22.04) ------------------------------
    {"intent": "show oracle instance metadata",            "command": "curl -s -H 'Authorization: Bearer OracleCloud' http://169.254.169.254/opc/v2/instance/metadata/ 2>/dev/null | head -50 || echo 'not on Oracle Cloud or metadata service unreachable'"},
    {"intent": "show apt packages with updates",           "command": "apt list --upgradable 2>/dev/null | head -20"},
    {"intent": "show ubuntu version",                      "command": "lsb_release -a 2>/dev/null || cat /etc/os-release | head -5"},
    {"intent": "show top 10 processes by memory",          "command": "ps aux --sort=-%mem | head -11"},
    {"intent": "show top 10 processes by cpu",             "command": "ps aux --sort=-%cpu | head -11"},
]


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def get_embedder():
    """Lazy-load the sentence-transformers model so import time stays fast."""
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


def embed(embedder, phrases: List[str]) -> List[List[float]]:
    """Encode a batch of phrases. Returns Python lists (LanceDB-friendly)."""
    vectors = embedder.encode(phrases, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

def get_table(db, *, create: bool = False):
    """Open the table, or create it empty if missing and create=True."""
    existing = db.list_tables().tables
    if LANCEDB_TABLE in existing:
        return db.open_table(LANCEDB_TABLE)
    if not create:
        raise FileNotFoundError(
            f"Table {LANCEDB_TABLE!r} not found in {LANCEDB_PATH}. "
            f"Run `python init_db.py` to create + seed it."
        )
    # LanceDB needs a sample row to infer schema. We use a zero-vector placeholder.
    return db.create_table(
        LANCEDB_TABLE,
        data=[{
            "id": "__schema_seed__",
            "intent_phrase": "",
            "command": "",
            "trust_score": 0.0,
            "success_count": 0,
            "failure_count": 0,
            "embedding": [0.0] * EMBEDDING_DIM,
        }],
        mode="create",
    )


def table_is_empty(table) -> bool:
    """True if the only row is the schema seed we used to create the table."""
    if table.count_rows() == 0:
        return True
    # Inspect just the id column to avoid pulling pandas/pyarrow conversion.
    rows = table.search().limit(1).where("id = '__schema_seed__'").to_list()
    if not rows:
        return False
    return rows[0]["id"] == "__schema_seed__" and table.count_rows() == 1


# ---------------------------------------------------------------------------
# Build / reset
# ---------------------------------------------------------------------------

def build(embedder, *, reset: bool = False) -> int:
    db = lancedb.connect(LANCEDB_PATH)
    Path(LANCEDB_PATH).mkdir(parents=True, exist_ok=True)

    if reset and LANCEDB_TABLE in db.list_tables().tables:
        print(f"[reset] dropping table {LANCEDB_TABLE!r}")
        db.drop_table(LANCEDB_TABLE)

    table = get_table(db, create=True)
    if not table_is_empty(table):
        existing = table.count_rows()
        print(f"[skip] table already has {existing} rows. Use --reset to rebuild.")
        return existing

    phrases = [c["intent"] for c in SEED_COMMANDS]
    print(f"[embed] encoding {len(phrases)} intent phrases with {EMBEDDING_MODEL} ...")
    vectors = embed(embedder, phrases)
    print(f"[embed] done. vector dim = {len(vectors[0])}")

    rows: List[Dict[str, Any]] = []
    for cmd, vec, phrase in zip(SEED_COMMANDS, vectors, phrases):
        rows.append({
            "id": str(uuid.uuid4()),
            "intent_phrase": phrase,
            "command": cmd["command"],
            "trust_score": TRUST_NEW,
            "success_count": 0,
            "failure_count": 0,
            "embedding": vec,
        })

    # If the schema seed row is present, delete it before adding real rows.
    if table.count_rows() == 1:
        seed_rows = table.search().limit(1).where("id = '__schema_seed__'").to_list()
        if seed_rows and seed_rows[0]["id"] == "__schema_seed__":
            table.delete("id = '__schema_seed__'")

    table.add(rows)
    print(f"[seed] inserted {len(rows)} commands. trust_score = {TRUST_NEW}")
    return len(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize the Lever-Runner LanceDB.")
    parser.add_argument("--reset", action="store_true",
                        help="Drop the existing table and rebuild from the seed pack. "
                             "Destructive: any commands you /teach'ed will be lost.")
    parser.add_argument("--yes", action="store_true",
                        help="Required with --reset. Skips the interactive confirm. "
                             "Prevents `install.sh` from wiping data on re-install.")
    args = parser.parse_args()

    if args.reset and not args.yes:
        print(
            "ERROR: --reset is destructive. It drops the existing table, "
            "wiping any commands you /teach'ed. Re-run with --reset --yes "
            "if you're sure.",
            file=sys.stderr,
        )
        return 2

    print(f"[init] lancedb path : {LANCEDB_PATH}")
    print(f"[init] table        : {LANCEDB_TABLE}")
    print(f"[init] embed model  : {EMBEDDING_MODEL}")

    embedder = get_embedder()
    n = build(embedder, reset=args.reset)
    print(f"[done] {n} commands in table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
