"""
auto_promote.py — the hourly self-improvement loop.

Run from cron:
    0 * * * *  cd /home/ubuntu/lever-runner && .venv/bin/python -m lever_runner.auto_promote

Two jobs:
    1) Bump trust on commands that are succeeding repeatedly.
    2) Find low-trust, failing commands. If a remote LLM key is configured,
       send the failing intent to it and ask for a corrected command. Insert
       the new candidate at trust=TRUST_REWRITTEN and soft-delete the old one.

If no remote LLM key is configured, step 2 is a no-op (we just keep stats).
This makes the script safe to run in a fresh install where the only LLM is
the local one used for intent extraction.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from .store import LANCEDB_PATH, LANCEDB_TABLE_PREFIX, CommandStore, LEGACY_TABLE
import lancedb

load_dotenv()

PROMOTE_FLOOR = float(os.getenv("TRUST_PROMOTE_FLOOR", "30"))
PROMOTE_FAILURES = int(os.getenv("TRUST_PROMOTE_FAILURES", "5"))
SUCCESS_BUMP_THRESHOLD = int(os.getenv("TRUST_SUCCESS_BUMP_THRESHOLD", "20"))
SUCCESS_BUMP_AMOUNT = float(os.getenv("TRUST_SUCCESS_BUMP_AMOUNT", "10"))
REWRITE_MODEL = os.getenv("REMOTE_LLM_MODEL", "claude-3-5-sonnet-latest")


def _all_rows(table):
    """Return every row as a list of dicts, dropping the schema seed.
    Uses search().to_list() rather than to_pandas() to avoid the pandas
    dependency (lancedb's to_pandas() triggers a pyarrow pandas shim
    that requires pandas to be importable)."""
    rows = table.search().limit(100000).to_list()
    return [r for r in rows if r["id"] != "__schema_seed__"]


def promote_winners(store: CommandStore) -> int:
    """Bump trust for commands that have been used a lot and are still below 90."""
    rows = _all_rows(store.table)
    n = 0
    for r in rows:
        if r["success_count"] > SUCCESS_BUMP_THRESHOLD and r["trust_score"] < 90:
            new_trust = min(100.0, r["trust_score"] + SUCCESS_BUMP_AMOUNT)
            store.table.update(
                where=f"id = '{r['id']}'",
                values={"trust_score": new_trust},
            )
            n += 1
    return n


def rewrite_with_remote_llm(intent: str, old_command: str, failure_count: int) -> str | None:
    """Ask a remote LLM to propose a corrected command. Returns the command
    string or None if no key is configured / call fails."""
    api_key = os.getenv("REMOTE_LLM_API_KEY", "")
    base_url = os.getenv("REMOTE_LLM_BASE_URL", "https://api.anthropic.com")
    if not api_key:
        return None

    system = (
        "You are fixing a shell command that has failed repeatedly. "
        "Output ONLY the corrected shell command on a single line, no markdown, "
        "no explanation, no code fences. Keep it simple and portable."
    )
    user = (
        f"intent: {intent}\n"
        f"failing command: {old_command}\n"
        f"failure count: {failure_count}\n\n"
        f"Propose a corrected command. One line, shell-only."
    )

    is_anthropic = "/anthropic" in base_url or base_url.endswith("anthropic.com")
    if is_anthropic:
        url = base_url.rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": REWRITE_MODEL,
            "max_tokens": 200,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    else:
        url = base_url.rstrip("/") + "/chat/completions"
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        body = {
            "model": REWRITE_MODEL,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    try:
        r = requests.post(url, headers=headers, json=body, timeout=30)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  remote-llm call failed: {e}", file=sys.stderr)
        return None

    data = r.json()
    if "content" in data:  # Anthropic
        text = data["content"][0]["text"]
    else:  # OpenAI
        text = data["choices"][0]["message"]["content"]
    return text.strip().splitlines()[0].strip()


def rewrite_losers(store: CommandStore) -> int:
    """Find low-trust failing commands, ask the remote LLM to fix them,
    insert the fix at trust=TRUST_REWRITTEN, soft-delete the old one."""
    rows = _all_rows(store.table)
    candidates = [
        r
        for r in rows
        if r["trust_score"] < PROMOTE_FLOOR and int(r["failure_count"]) >= PROMOTE_FAILURES
    ]
    if not candidates:
        return 0
    n = 0
    for r in candidates:
        new_cmd = rewrite_with_remote_llm(r["intent_phrase"], r["command"], int(r["failure_count"]))
        if not new_cmd or new_cmd == r["command"]:
            continue
        # Insert the rewrite at trust=40 (TRUST_REWRITTEN), soft-delete old.
        try:
            store.teach(r["intent_phrase"], new_cmd, trust=store.TRUST_REWRITTEN)
        except Exception as e:
            print(f"  insert failed: {e}", file=sys.stderr)
            continue
        store.soft_delete(r["id"])
        n += 1
        print(f"  rewrote: {r['intent_phrase']!r}  {r['command']!r}  ->  {new_cmd!r}")
    if not candidates:
        print("  (no low-trust failing commands)")
    elif not os.getenv("REMOTE_LLM_API_KEY"):
        print(f"  ({len(candidates)} candidates; set REMOTE_LLM_API_KEY to rewrite)")
    return n


def _iter_chat_tables():
    """Yield (chat_id, CommandStore) for every commands_* table in the DB.

    With v0.2 per-chat isolation, a single global sweep no longer covers
    all chats. We discover tables at runtime by listing them in the
    LanceDB directory and instantiating a CommandStore for each. The
    'default' chat uses the legacy single-table name to preserve data
    across upgrades (see store._migrate_legacy_table_if_needed).
    """
    Path(LANCEDB_PATH).mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(LANCEDB_PATH)
    for name in sorted(db.list_tables().tables):
        if name == LEGACY_TABLE:
            chat_id = "default"
        elif name.startswith(f"{LANCEDB_TABLE_PREFIX}_"):
            chat_id = name[len(LANCEDB_TABLE_PREFIX) + 1:]
        else:
            continue
        yield chat_id, CommandStore(chat_id=chat_id)


def main() -> int:
    total_promoted = 0
    total_rewritten = 0
    for chat_id, store in _iter_chat_tables():
        n = store.count()
        print(f"[auto_promote] chat={chat_id}  {n} commands in table")
        p = promote_winners(store)
        r = rewrite_losers(store)
        print(f"[auto_promote] chat={chat_id}  +{p} promoted  +{r} rewritten")
        total_promoted += p
        total_rewritten += r
    print(f"[auto_promote] total: +{total_promoted} promoted, +{total_rewritten} rewritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
