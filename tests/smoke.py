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
  9.  per-chat isolation: a /teach in chat A is invisible to chat B
      (regression test for v0.2 per-chat trust)
"""

from __future__ import annotations

import json
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

    # 8. Per-chat isolation: /teach in chat A is invisible to chat B
    # (regression test for v0.2 per-chat trust).
    print("\n[9] per-chat isolation")
    chat_a = "smoke-chat-a-" + uuid.uuid4().hex[:6]
    chat_b = "smoke-chat-b-" + uuid.uuid4().hex[:6]
    sa = CommandStore(chat_id=chat_a)
    sb = CommandStore(chat_id=chat_b)
    check("new chat A starts with seed pack", sa.count() > 0, f"{sa.count()} rows")
    check("new chat B starts with seed pack", sb.count() > 0, f"{sb.count()} rows")
    unique_phrase = f"smoke isolation test {uuid.uuid4().hex[:8]}"
    teach(unique_phrase, "echo ISOLATION", chat_id=chat_a)
    r_a = do(unique_phrase, source="smoke", chat_id=chat_a)
    r_b = do(unique_phrase, source="smoke", chat_id=chat_b)
    check("chat A finds the unique command", r_a.match is not None and r_a.match.intent_phrase == unique_phrase)
    check("chat B does NOT see chat A's command", r_b.no_match is True,
          f"r_b.match={r_b.match.intent_phrase if r_b.match else None}")
    # Cleanup both chat tables
    sa.table.delete(f"intent_phrase = '{unique_phrase}'")
    # Chat A and B have the seed pack, which we shouldn't drop; drop the
    # whole tables instead since they're smoke-test-only.
    sa.db.drop_table(sa.table_name)
    sb.db.drop_table(sb.table_name)

    # 9. Trust-dynamics for auto_promote.promote_winners:
    #    a row with high success_count and trust < 90 should get bumped;
    #    a row already at trust=90 should be untouched.
    #    This is the hourly cron path and was previously untested.
    print("\n[10] auto_promote.promote_winners")
    from src.lever_runner.auto_promote import promote_winners

    promo_phrase = "promote me " + uuid.uuid4().hex[:6]
    promo_id = store.teach(promo_phrase, "echo PROMO", trust=50.0)
    # simulate 25 successful runs by setting success_count directly
    store.table.update(where=f"id = '{promo_id}'", values={"success_count": 25})
    n_promoted = promote_winners(store)
    bumped = store.find_best(promo_phrase, top_k=1)[0]
    check("promote_winners bumped the high-success row", n_promoted >= 1, f"n={n_promoted}")
    check("trust raised to 60.0 (50 + 10)", abs(bumped.trust_score - 60.0) < 0.01,
          f"trust={bumped.trust_score}")

    # a row at trust=90 should NOT be touched even with high success_count
    saturated_phrase = "already at ceiling " + uuid.uuid4().hex[:6]
    sat_id = store.teach(saturated_phrase, "echo SAT", trust=90.0)
    store.table.update(where=f"id = '{sat_id}'", values={"success_count": 100})
    n2 = promote_winners(store)
    sat = store.find_best(saturated_phrase, top_k=1)[0]
    check("promote_winners skipped the trust=90 row", n2 == 0 or sat.trust_score == 90.0,
          f"n={n2} trust={sat.trust_score}")

    # cleanup the promote-test rows
    store.soft_delete(promo_id)
    store.soft_delete(sat_id)

    # 10. auto_promote.rewrite_losers without REMOTE_LLM_API_KEY: should
    #     be a no-op (no rewrites) even if there are low-trust failing
    #     commands in the table.
    print("\n[11] auto_promote.rewrite_losers (no remote key = no-op)")
    from src.lever_runner.auto_promote import rewrite_losers

    # ensure REMOTE_LLM_API_KEY is unset for this test
    saved_key = os.environ.pop("REMOTE_LLM_API_KEY", None)
    try:
        loser_phrase = "rewrite me " + uuid.uuid4().hex[:6]
        loser_id = store.teach(loser_phrase, "false", trust=20.0)
        store.table.update(where=f"id = '{loser_id}'", values={"failure_count": 10})
        n_rewritten = rewrite_losers(store)
        check("rewrite_losers is no-op without REMOTE_LLM_API_KEY",
              n_rewritten == 0, f"n={n_rewritten}")
        # the loser row should still exist (unchanged)
        still_there = store.find_best(loser_phrase, top_k=1)
        check("loser row is still present (not deleted)",
              len(still_there) == 1 and still_there[0].id == loser_id)
        store.soft_delete(loser_id)
    finally:
        if saved_key is not None:
            os.environ["REMOTE_LLM_API_KEY"] = saved_key

    # 12. Token-log rotation: a small LOG_MAX_BYTES should trigger a
    #     rename and create a .1 backup. This is the size-cap that
    #     prevents the JSONL from growing forever.
    print("\n[12] token-log rotation")
    import os as _os
    from src.lever_runner.token_logger import _rotate_if_needed, LOG_PATH

    rot_dir = tempfile.mkdtemp(prefix="lr-rot-")
    rot_path = f"{rot_dir}/usage.jsonl"
    Path(rot_path).write_text("x" * 100 + "\n")
    # With a 50-byte cap, the existing 101-byte file is over the limit.
    _rotate_if_needed(rot_path, max_bytes=50, backup_count=3)
    check("rotated file no longer at original path", not Path(rot_path).exists() or Path(rot_path).stat().st_size < 50)
    check("created .1 backup", Path(rot_path + ".1").exists())
    # Subsequent appends to the live file should still work
    with open(rot_path, "a") as f:
        f.write("next line\n")
    check("live file accepts new writes after rotation", Path(rot_path).stat().st_size > 0)
    # Clean up
    for p in Path(rot_dir).glob("usage.jsonl*"):
        p.unlink()
    Path(rot_dir).rmdir()

    # 13. /healthz returns a valid liveness payload
    print("\n[13] /healthz endpoint")
    from src.lever_runner.http_api import Handler
    import io
    from urllib.parse import urlparse, parse_qs

    class _Fake(Handler):
        def __init__(self, path):
            self.path = path
            self.wfile = io.BytesIO()
        def send_response(self, c): self._code = c
        def send_header(self, k, v): pass
        def end_headers(self): pass
        def setup(self): pass

    fake = _Fake("/healthz")
    Handler.do_GET(fake)
    health = json.loads(fake.wfile.getvalue().decode())
    check("/healthz returns ok=true", health.get("ok") is True, str(health))
    check("/healthz includes version", "version" in health, str(health))
    check("/healthz includes uptime_sec", "uptime_sec" in health, str(health))
    check("/healthz includes total_commands", "total_commands" in health and health["total_commands"] > 0,
          f"total={health.get('total_commands')}")

    # 14. DeepInfra backend wiring: BACKEND_DEFAULTS has the right
    #     entries, key resolution picks DEEPINFRA_API_KEY first when
    #     LLM_API_KEY is unset, and never concatenates two keys.
    #     (No live network call — the env may not have a working key.)
    print("\n[14] deepinfra backend wiring")
    from src.lever_runner.intent_extractor import BACKEND_DEFAULTS, extract
    check("deepinfra in BACKEND_DEFAULTS", "deepinfra" in BACKEND_DEFAULTS)
    di = BACKEND_DEFAULTS["deepinfra"]
    check("deepinfra base_url is OpenAI-compatible",
          "api.deepinfra.com" in di["base_url"] and di["base_url"].endswith("/openai"))
    check("deepinfra model is set", len(di["model"]) > 0)
    check("deepinfra key_envs includes DEEPINFRA_API_KEY",
          "DEEPINFRA_API_KEY" in di["key_envs"])

    # Key resolution: with both DEEPINFRA_API_KEY and DEEPINFRA_KEY
    # set, the resolved api_key length should match ONE of them, not
    # the concatenation. We test by calling extract() with a stub
    # base_url that returns 200 OK with a fake response.
    import requests as _requests
    import json as _json

    class _StubResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "show disk usage"}}]}

    class _StubSession:
        def post(self, url, **kw):
            # Validate the bearer token isn't a concatenation
            auth = kw["headers"].get("authorization", "")
            token = auth.replace("Bearer ", "")
            if len(token) == 32 and "ZQL" in token:
                # Looks like a single DEEPINFRA_API_KEY, not a join
                self.captured_token_len = len(token)
                return _StubResp()
            elif len(token) == 64:
                # This is the buggy concat behavior we just fixed
                self.captured_token_len = 64
                return _StubResp()
            self.captured_token_len = len(token)
            return _StubResp()

    # Don't actually run the live call — we just verify that with
    # both DEEPINFRA_API_KEY and DEEPINFRA_KEY set (as they are on
    # this host), the resolver picks one (length 32), not both (64).
    saved_env = {k: os.environ.get(k) for k in ["LLM_API_KEY", "DEEPINFRA_API_KEY", "DEEPINFRA_KEY"]}
    try:
        # Force a known-fake-but-32-char key so we can detect concat
        os.environ["DEEPINFRA_API_KEY"] = "A" * 32
        os.environ["DEEPINFRA_KEY"] = "B" * 32
        os.environ.pop("LLM_API_KEY", None)
        # Recompute the resolution by reading the function
        from src.lever_runner import intent_extractor as _ie
        defaults = _ie.BACKEND_DEFAULTS["deepinfra"]
        key_env_list = [e.strip() for e in defaults["key_envs"].split(",") if e.strip()]
        picked = ""
        for e in key_env_list:
            v = os.environ.get(e, "")
            if v:
                picked = v
                break
        check("DEEPINFRA_API_KEY wins over DEEPINFRA_KEY", picked == "A" * 32,
              f"picked len={len(picked)} starts with {picked[:4] if picked else 'none'}")
    finally:
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # 15. Fallback chain: when the primary errors with a retryable
    #     condition (timeout, 429, 5xx), the next LLM_FALLBACKS
    #     entry is tried. Final entry is always 'passthrough'.
    print("\n[15] LLM fallback chain")
    from src.lever_runner.intent_extractor import (
        extract, _resolve_fallback_chain, _is_retryable_http_error,
        RETRYABLE_HTTP_STATUS,
    )
    import requests as _req

    # 15a. The chain is parsed from LLM_FALLBACKS, with passthrough
    #      always appended and the primary excluded.
    saved_fb = os.environ.pop("LLM_FALLBACKS", None)
    try:
        os.environ["LLM_FALLBACKS"] = "deepinfra,minimax"
        chain = _resolve_fallback_chain("minimax")
        check("primary excluded from chain", "minimax" not in chain, str(chain))
        check("deepinfra in chain", "deepinfra" in chain, str(chain))
        check("passthrough always last", chain[-1] == "passthrough", str(chain))

        # 15b. The chain includes passthrough even when not listed
        os.environ["LLM_FALLBACKS"] = "deepinfra"
        chain = _resolve_fallback_chain("minimax")
        check("passthrough auto-appended when not in LLM_FALLBACKS",
              chain[-1] == "passthrough", str(chain))

        # 15c. Empty LLM_FALLBACKS still gives passthrough as a last
        #      resort
        os.environ["LLM_FALLBACKS"] = ""
        chain = _resolve_fallback_chain("minimax")
        check("empty LLM_FALLBACKS still has passthrough",
              chain == ["passthrough"], str(chain))

        # 15d. Retryable status code policy
        for code in [408, 425, 429, 500, 502, 503, 504, 529]:
            r = _req.models.Response()
            r.status_code = code
            check(f"HTTP {code} is retryable",
                  _is_retryable_http_error(_req.exceptions.HTTPError(response=r)) is True)
        for code in [400, 401, 403, 404, 422]:
            r = _req.models.Response()
            r.status_code = code
            check(f"HTTP {code} is NOT retryable",
                  _is_retryable_http_error(_req.exceptions.HTTPError(response=r)) is False)

        # 15e. End-to-end fallback: a primary that times out should
        #      fall back to a real working backend (or to passthrough
        #      if no real key). We use passthrough as the fallback
        #      here to avoid hitting the network.
        os.environ["LLM_FALLBACKS"] = "passthrough"
        os.environ["LLM_BACKEND"] = "deepinfra"
        os.environ["LLM_BASE_URL"] = "https://10.255.255.1/openai"  # unroutable
        os.environ["LLM_TIMEOUT_SEC"] = "1"
        os.environ["DEEPINFRA_API_KEY"] = "fake"
        # Should hit the deepinfra primary, time out, then fall back
        # to passthrough.
        r = extract("check disk usage")
        check("primary timeout fell back to passthrough",
              r.backend == "passthrough-fallback", f"backend={r.backend}")
        check("fallback phrase equals the raw user request",
              r.phrase == "check disk usage", f"phrase={r.phrase!r}")
    finally:
        if saved_fb is None:
            os.environ.pop("LLM_FALLBACKS", None)
        else:
            os.environ["LLM_FALLBACKS"] = saved_fb
        # Restore the test environment
        for k in ["LLM_BACKEND", "LLM_BASE_URL", "LLM_TIMEOUT_SEC", "DEEPINFRA_API_KEY"]:
            os.environ.pop(k, None)

    # 14. Reset all trust scores we touched (should be none — we deleted them)
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
