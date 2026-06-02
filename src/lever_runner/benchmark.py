"""
benchmark.py — fixed 20-task suite. Run with:

    python -m lever_runner.benchmark

Reports the average token cost per executed command. The headline target
is < 200 tokens per command. We force `LLM_BACKEND=passthrough` so the
test doesn't depend on having a remote API key — we measure *embedding*
token use plus the *intent-system-prompt* token use, which is what the
< 200 claim is really about. The actual LLM call cost is bounded by
extractor's SYSTEM_PROMPT (~ 60 in / 8 out), which we add to the
"intent" total in the report.
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from typing import List, Tuple

from dotenv import load_dotenv

# Force the benchmark to skip real LLM calls.
os.environ["LLM_BACKEND"] = "passthrough"
load_dotenv()

from . import token_logger                    # noqa: E402
from .orchestrator import do, CommandStore    # noqa: E402


TASKS: List[str] = [
    "check disk usage",
    "show memory usage",
    "running processes",
    "is the server up",
    "list docker containers",
    "show all docker containers",
    "git status",
    "show recent git commits",
    "what's my ip address",
    "show python version",
    "show node version",
    "show kernel and hostname",
    "show system uptime",
    "list npm global packages",
    "show disk usage by directory",
    "audit npm dependencies",
    "show docker images",
    "list running systemd services",
    "show failed systemd services",
    "show ollama models",
]


def main() -> int:
    # Fresh log files for this run.
    for p in (token_logger.LOG_PATH, token_logger.EMBED_LOG_PATH):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    # Wipe the table so trust scores don't drift between runs.
    import lancedb
    db = lancedb.connect(os.getenv("LANCEDB_PATH", "./data/lever.lancedb"))
    table_name = os.getenv("LANCEDB_TABLE", "commands")
    if table_name in db.list_tables().tables:
        db.drop_table(table_name)
    # Re-seed by invoking init_db.py in-process.
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from init_db import build, get_embedder  # type: ignore
    build(get_embedder(), reset=True)

    store = CommandStore()
    print(f"benchmark: {len(TASKS)} tasks, {store.count()} commands in table")
    print(f"backend   : passthrough (no real LLM calls)")
    print(f"embedding : {os.getenv('EMBEDDING_MODEL')}")
    print()

    per_task: List[Tuple[str, int, int, bool]] = []
    for i, task in enumerate(TASKS, 1):
        r = do(task, source=f"bench-{i}", store=store)
        status = "ok" if r.ok else "FAIL"
        print(f"  {i:>2}. [{status}] {task!r:45s}  intent={r.intent!r}  tokens={r.total_tokens}")
        per_task.append((task, r.tokens_in, r.tokens_out, r.ok))

    intent_totals = [t[1] + t[2] for t in per_task]
    successes = sum(1 for t in per_task if t[3])

    # Embedding cost: read the JSONL we just wrote.
    embed_tokens = 0
    embed_count = 0
    try:
        with open(token_logger.EMBED_LOG_PATH) as f:
            for line in f:
                import json
                rec = json.loads(line)
                embed_tokens += int(rec.get("tokens", 0))
                embed_count += 1
    except FileNotFoundError:
        pass

    intent_avg = statistics.mean(intent_totals) if intent_totals else 0
    embed_avg = (embed_tokens / embed_count) if embed_count else 0
    grand_avg = intent_avg + embed_avg

    print()
    print("=" * 60)
    print(f"tasks run           : {len(TASKS)}")
    print(f"successes           : {successes}/{len(TASKS)}")
    print(f"avg intent tokens   : {intent_avg:.1f}  (in + out of LLM)")
    print(f"avg embed tokens    : {embed_avg:.1f}  (per intent phrase)")
    print(f"avg total per cmd   : {grand_avg:.1f}")
    print(f"target              : < 200")
    print("=" * 60)
    return 0 if grand_avg < 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
