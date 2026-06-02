"""
seed_import.py — import commands from a JSONL skill pack.

Each line of input must be a JSON object with at least:

    {"intent_phrase": str, "command": str}

Optional fields override the defaults:

    trust_score   (default 50)   — initial trust for the imported row
    success_count (default 0)
    failure_count (default 0)

Embeddings are computed locally on import. Use --reset to drop the
existing table first (DANGEROUS: deletes all current rows).

Usage:
    python -m lever_runner.seed_import my-skillpack.jsonl
    python -m lever_runner.seed_import --trust 30 pack.jsonl
    curl -sL https://example.com/pack.jsonl | python -m lever_runner.seed_import
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable

from .store import CommandStore


def _iter_jsonl(stream) -> Iterable[dict]:
    for i, line in enumerate(stream, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  line {i}: skipping bad JSON: {e}", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser(description="Import lever-runner commands from JSONL.")
    p.add_argument("file", nargs="?", default="-", help="input file or '-' for stdin (default)")
    p.add_argument(
        "--trust", type=float, default=50.0, help="default trust for rows that don't specify one"
    )
    p.add_argument(
        "--reset", action="store_true", help="DANGEROUS: drop the existing table before importing"
    )
    p.add_argument(
        "--skip-existing",
        action="store_true",
        help="skip rows whose intent_phrase already exists in the table",
    )
    args = p.parse_args()

    store = CommandStore()
    if args.reset:
        print("[reset] dropping existing table", file=sys.stderr)
        store.db.drop_table(store.db.list_tables().tables[0])  # drop the only table
        store = CommandStore()  # re-init empty

    if args.skip_existing:
        existing_phrases = {
            r["intent_phrase"]
            for r in store.table.search().limit(100000).to_list()
            if r["id"] != "__schema_seed__"
        }
    else:
        existing_phrases = set()

    if args.file == "-":
        records = list(_iter_jsonl(sys.stdin))
    else:
        with open(args.file, encoding="utf-8") as f:
            records = list(_iter_jsonl(f))

    n_in = len(records)
    n_out = 0
    n_skipped = 0
    for r in records:
        phrase = (r.get("intent_phrase") or "").strip()
        cmd = (r.get("command") or "").strip()
        if not phrase or not cmd:
            n_skipped += 1
            continue
        if phrase in existing_phrases:
            n_skipped += 1
            continue
        trust = float(r.get("trust_score", args.trust))
        store.teach(phrase, cmd, trust=trust)
        n_out += 1
        existing_phrases.add(phrase)

    print(
        f"[import] {n_out}/{n_in} rows inserted, {n_skipped} skipped "
        f"(file={args.file}, reset={args.reset}, skip-existing={args.skip_existing})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
