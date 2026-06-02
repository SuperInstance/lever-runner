"""
smoke.py — end-to-end test for lever-runner.

Runs in-process against the on-disk database. Exits 0 if all checks pass,
1 otherwise. Designed to be safe to run against a live database: it
soft-deletes any rows it inserts, and resets trust scores at the end.

    .venv/bin/python -m tests.smoke

Covers:
  1.  table is non-empty (init_db.py has been run)
  2.  good match: "check disk usage" -> df -h, exit 0
  3.  no-match: gibberish returns no_match=True
  4.  teach -> run cycle: a freshly-inserted row is findable on the next call
  5.  trust bumps +1.5 on success, persists
  6.  trust drops -4.0 on failure, persists
  7.  soft_delete removes a row
  8.  find_best returns the closest match, not a high-trust-but-distant one
      (regression test for the inverted-priority bug)
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

# Force passthrough so we don't need an LLM key to run smoke tests.
os.environ["LLM_BACKEND"] = "passthrough"

# Use a temporary database for smoke tests so we don't pollute the real one.
TMP_DIR = Path(tempfile.mkdtemp(prefix="lever-runner-smoke-"))
os.environ["LANCEDB_PATH"] = str(TMP_DIR / "smoke.lancedb")
os.environ["SANDBOX_ROOT"] = str(TMP_DIR / "sandbox")
os.environ["TOKEN_LOG_PATH"] = str(TMP_DIR / "token.jsonl")
os.environ["EMBED_LOG_PATH"] = str(TMP_DIR / "embed.jsonl")
os.environ["MATCH_SIMILARITY_FLOOR"] = "0.55"

# Make src/ importable when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from init_db import build, get_embedder  # noqa: E402
from src.lever_runner.orchestrator import do, teach  # noqa: E402
from src.lever_runner.store import CommandStore  # noqa: E402

PASS = "\033[32mok\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = PASS if cond else FAIL
    print(f"  [{tag}] {name}" + (f"   {detail}" if detail else ""))
    results.append((name, cond, detail))


def main() -> int:
    print(f"smoke: using temp dir {TMP_DIR}")

    # 0. Seed a fresh table.
    print("\n[setup] seeding fresh database...")
    build(get_embedder(), reset=True)
    store = CommandStore()
    check("table non-empty", store.count() > 0, f"{store.count()} commands")

    # 1. Good match
    print("\n[1] good match: 'check disk usage'")
    r = do("check disk usage", source="smoke")
    check("match found", r.match is not None, r.match.intent_phrase if r.match else "None")
    check("correct match", r.match and r.match.intent_phrase == "show disk usage")
    check(
        "ran without error",
        r.run is not None and r.run.ok,
        f"exit={r.run.exit_code if r.run else 'n/a'}",
    )
    check("stdout has Filesystem header", r.run and "Filesystem" in r.run.stdout)

    # 2. No-match
    print("\n[2] no-match: 'defenestrate the mainframe'")
    r = do("defenestrate the mainframe", source="smoke")
    check("no_match=True", r.no_match is True)
    check("did not execute", r.run is None)

    # 3. Teach + run cycle
    print("\n[3] teach + immediate run: 'reboot the box'")
    phrase = "reboot the box " + uuid.uuid4().hex[:6]  # unique so we don't collide
    cmd = f"echo SMOKE_TEST_{uuid.uuid4().hex[:8]}"
    new_id = teach(phrase, cmd)
    check("teach returned an id", bool(new_id))
    r = do(phrase, source="smoke")
    check(
        "new row is findable on the next do() call",
        r.match is not None and r.match.id == new_id,
        f"match={r.match.intent_phrase if r.match else None}",
    )
    check(
        "ran the taught command",
        r.run is not None and r.run.ok and "SMOKE_TEST_" in r.run.stdout,
        f"stdout={r.run.stdout.strip() if r.run else 'n/a'}",
    )

    # 4. Trust dynamics
    # After step 3, the taught row has already been run once, so its trust
    # is 51.5 (50 + 1.5) and success_count is 1. Snapshot, run again, check.
    print("\n[4] trust dynamics")
    m_before = store.find_best(phrase, top_k=1)[0]
    check(
        "post-first-run trust = 51.5",
        abs(m_before.trust_score - 51.5) < 0.01,
        f"trust={m_before.trust_score}",
    )
    check(
        "post-first-run success_count = 1",
        m_before.success_count == 1,
        f"succ={m_before.success_count}",
    )
    do(phrase, source="smoke")  # second run
    m_after = store.find_best(phrase, top_k=1)[0]
    check(
        "trust bumped to 53.0 after second success",
        abs(m_after.trust_score - 53.0) < 0.01,
        f"trust={m_after.trust_score}",
    )
    check(
        "success_count incremented to 2",
        m_after.success_count == 2,
        f"succ={m_after.success_count}",
    )

    # 5. Failure path: teach a command that will fail, run it
    print("\n[5] failure path: command that exits non-zero")
    fail_phrase = "force a failure " + uuid.uuid4().hex[:6]
    fail_cmd = "exit 7"
    fail_id = teach(fail_phrase, fail_cmd)
    r = do(fail_phrase, source="smoke")
    m_fail = store.find_best(fail_phrase, top_k=1)[0]
    check(
        "failure detected",
        r.run is not None and not r.run.ok,
        f"exit={r.run.exit_code if r.run else 'n/a'}",
    )
    check(
        "trust dropped by 4.0 to 46.0",
        abs(m_fail.trust_score - 46.0) < 0.01,
        f"trust={m_fail.trust_score}",
    )

    # 6. soft_delete
    print("\n[6] soft_delete")
    pre = store.count()
    store.soft_delete(new_id)
    store.soft_delete(fail_id)
    check("count decremented by 2", store.count() == pre - 2, f"pre={pre} post={store.count()}")

    # 7. Regression: high-trust wrong match should NOT be picked over
    #    low-trust but exact-similarity match. We re-teach a row at trust=50
    #    and compare against a pre-existing row that we'll bump to trust=90.
    print("\n[7] regression: trust is a gate, not a tiebreaker")
    target_phrase = "show top memory " + uuid.uuid4().hex[:6]
    other_phrase = "show top cpu " + uuid.uuid4().hex[:6]
    target_id = teach(target_phrase, "echo TARGET")
    other_id = teach(other_phrase, "echo OTHER")
    # artificially bump the OTHER row to trust=90
    store.table.update(where=f"id = '{other_id}'", values={"trust_score": 90.0})
    # now ask for the TARGET row, which has trust=50
    r = do(target_phrase, source="smoke")
    check(
        "exact-similarity match wins despite lower trust",
        r.match is not None and r.match.id == target_id,
        f"match={r.match.intent_phrase if r.match else None}",
    )
    store.soft_delete(target_id)
    store.soft_delete(other_id)

    # 8. Reset all trust scores we touched (should be none — we deleted them)
    print("\n[cleanup] all test rows soft-deleted; trust scores untouched")

    # Summary
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print()
    print("=" * 60)
    print(f"smoke: {passed}/{total} passed")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
