"""
seed_export.py — export the current LanceDB table to JSONL.

Each line is a JSON object with the schema:

    {"intent_phrase": str, "command": str, "trust_score": float,
     "success_count": int, "failure_count": int}

Embeddings are NOT exported; the importer re-encodes on its machine.
This keeps the export file small (no 384-dim float arrays per row).

Usage:
    python -m lever_runner.seed_export > my-skillpack.jsonl
    python -m lever_runner.seed_export --min-trust 70 > trusted-only.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys

from .store import CommandStore


def main() -> int:
    p = argparse.ArgumentParser(description="Export lever-runner commands to JSONL.")
    p.add_argument(
        "--min-trust",
        type=float,
        default=0.0,
        help="only export rows with trust_score >= this (default 0)",
    )
    p.add_argument(
        "--include-stats",
        action="store_true",
        help="include trust/success/failure counts in the export",
    )
    args = p.parse_args()

    store = CommandStore()
    rows = store.table.search().limit(100000).to_list()
    n_in = n_out = 0
    for r in rows:
        if r["id"] == "__schema_seed__":
            continue
        n_in += 1
        if r["trust_score"] < args.min_trust:
            continue
        rec = {
            "intent_phrase": r["intent_phrase"],
            "command": r["command"],
        }
        if args.include_stats:
            rec["trust_score"] = r["trust_score"]
            rec["success_count"] = r["success_count"]
            rec["failure_count"] = r["failure_count"]
        json.dump(rec, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        n_out += 1

    print(
        f"# exported {n_out}/{n_in} rows "
        f"(min-trust={args.min_trust}, include-stats={args.include_stats})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
