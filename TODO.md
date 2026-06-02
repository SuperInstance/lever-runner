# TODO — what I'd want for v0.4

A list of things I noticed during the v0.3 build but deliberately
didn't do. Not a roadmap — just a place to put the "if I had more
time" notes so they don't get lost.

## Done in v0.3.1

- ✅ `/commands [N] [--page=K]` — paginated table listing, sorted
  by trust desc. Bot + CLI (via `orchestrator.list_commands`).
- ✅ `/stats <phrase>` — full stats for one command: trust,
  success/failure counts, created/last_run, embedding distance.
  Respects MATCH_SIMILARITY_FLOOR (returns "no match" with
  context below the floor).
- ✅ `/teach --trust=N` — override starting trust. Bot + CLI.
  Validates 0-100 range.
- ✅ `store.list_all(limit, offset, min_trust)` — new method on
  CommandStore; uses lancedb's `.to_pandas()` for filtering +
  sorting. Pagination is Python-side because the tables are
  O(hundreds) rows and lancedb's pagination semantics vary.
- ✅ `store.get_by_id(row_id)` — fetch one row's full metadata.
- ✅ pandas added to requirements.txt.

## Done in v0.3.0

- ✅ **DeepInfra backend.** New `LLM_BACKEND=deepinfra` path uses
  the OpenAI-compatible API at `api.deepinfra.com`. Default
  model: `meta-llama/Meta-Llama-3.1-8B-Instruct` (clean
  instruction-follower; the Qwen3.5-4B is a reasoning model
  whose `content` ends up empty, so it can't be used as a phrase
  compressor).
- ✅ **Provider fallback chain.** `LLM_FALLBACKS` env var (default
  `deepinfra`) sets a comma-separated list of backends tried in
  order when the primary errors. Retryable: timeout, 429, 5xx,
  502, 503, 504, 529. 401 also falls through to the next backend.
  4xx other than 401 propagate up.
- ✅ **Per-backend URL/model env vars.** `LLM_MINIMAX_BASE_URL`,
  `LLM_DEEPINFRA_BASE_URL`, etc. — the global `LLM_BASE_URL` no
  longer leaks into fallback attempts.
- ✅ **Key resolution bug fix.** The previous `or "".join(...)`
  code concatenated two env vars into a 64-char invalid key when
  both were set. Replaced with first-non-empty-wins.

- ✅ **DeepInfra backend.** New `LLM_BACKEND=deepinfra` path uses
  the OpenAI-compatible API at `api.deepinfra.com`. Default
  model: `meta-llama/Meta-Llama-3.1-8B-Instruct` (clean
  instruction-follower; the Qwen3.5-4B is a reasoning model
  whose `content` ends up empty, so it can't be used as a phrase
  compressor).
- ✅ **Provider fallback chain.** `LLM_FALLBACKS` env var (default
  `deepinfra`) sets a comma-separated list of backends tried in
  order when the primary errors. Retryable: timeout, 429, 5xx,
  502, 503, 504, 529. 401 also falls through to the next backend.
  4xx other than 401 propagate up.
- ✅ **Per-backend URL/model env vars.** `LLM_MINIMAX_BASE_URL`,
  `LLM_DEEPINFRA_BASE_URL`, etc. — the global `LLM_BASE_URL` no
  longer leaks into fallback attempts.
- ✅ **Key resolution bug fix.** The previous `or "".join(...)`
  code concatenated two env vars into a 64-char invalid key when
  both were set. Replaced with first-non-empty-wins.
- ✅ **Tests: 59/59** (was 34 in v0.2). New: 8 retryable-status
  checks, 4 chain-parsing checks, 1 end-to-end
  primary-timeout-falls-back-to-passthrough check, plus the
  existing 34 from v0.2.

## Done in v0.2

- ✅ Per-chat trust isolation (chat-scoped LanceDB tables, default = "default")
- ✅ LLM request timeout (5s, with passthrough fallback so a hung
  LLM can't hang the orchestrator)
- ✅ Log rotation for token_usage.jsonl / embed_usage.jsonl (5 MiB
  cap, 3 backups, ~20 MiB max per log)
- ✅ GET /healthz endpoint (version, uptime, table counts)
- ✅ Trust-dynamics tests for `auto_promote.py` (cron path now has
  coverage in `tests/smoke.py`)

## Correctness / robustness (v0.3 candidates)

- **Race-condition test for read-after-write.** We saw the
  LanceDB read-after-write race during the v0.1.0 build (teach +
  immediate do returned the wrong row). The fix was
  `read_consistency_interval=0`, but the test would need to
  reproduce the race deterministically, which is hard. Worth
  trying with a stress test that does `teach` + `do` 100 times in
  a loop.
- **Concurrent `/teach` from multiple chat IDs.** v0.2 added
  per-chat isolation but the write path is still global
  serialization through lancedb. Two users in different chats
  `/teach`ing simultaneously is fine (different tables), but
  within a chat, concurrent `/teach` is racy on the row id.
  Low priority — there's only one user right now.
- **`/do` after bot restart race.** The bot reads the table on
  every command. If LanceDB's index hasn't refreshed after a
  teach from a previous run, `/do` could miss it. The
  `read_consistency_interval=0` covers most cases but a forced
  re-open on table change would be belt-and-suspenders.

## Operational (v0.3 candidates)

- **Secret rotation helper.** A `make rotate-telegram-token` that
  walks you through @BotFather, then updates `.env` and restarts
  the systemd unit. Or just: rotate the four exposed keys
  (Telegram, MINIMAX, DEEPINFRA, ZAI) manually.
- **Bot log rotation.** Bot logs go to journald (great), but
  `logs/auto_promote.log` and `logs/bot.log` (the stale one
  from before we relied on journald) need a logrotate config.
  Lower priority than the JSONL rotation we just shipped.
- **Token budget on the LLM call.** `intent_extractor` doesn't
  enforce a max output token count. We hard-coded `max_tokens=32`
  in the request, but a hostile or buggy provider could ignore
  it. Add a server-side cap on returned content length.

## Features (v0.3 candidates)

- **`/teach --trust=70`** to override the default trust when
  teaching. Useful for "I know this is a good command, start
  it higher than 50."
- **`/commands`** — list the table (paginated). Useful from
  Telegram when you forget what's seeded.
- **`/stats <intent-phrase>`** — show trust, success_count,
  failure_count, last_run for a specific command. Useful for
  debugging.
- **Skill pack signing.** `community/k8s-ops.jsonl` is currently
  unsigned; if someone MITMs your download they can swap a
  command. A `sha256` + minisign signature per pack would be
  better.
- **Multi-language intents.** Right now intents are English. With
  `paraphrase-multilingual-MiniLM-L12-v2` (470MB) the same
  architecture works for any language, but that's a v0.3
  decision.
- **A tiny web UI** that shows the table, lets you `/teach` from
  the browser, and shows recent runs. Not the static landing
  page; an actual SPA-ish thing. v0.3 at earliest.

## Code quality (v0.3 candidates)

- **`bot.py` test coverage.** The handlers are all unit-testable
  with a mock `Update` object. There are zero tests for `bot.py`
  today. v0.3 should add at least: allowed-user gate, /do happy
  path, /teach happy path, /status happy path.
- **`intent_extractor.py` test coverage.** The 4 backends should
  each have a happy-path test and a "backend down" test. We added
  a single timeout fallback test in v0.2; expand to all backends.
- **The benchmark's pass count is 14/20** which is honest but
  low. Add more seeds or relax the similarity floor — but the
  trade-off is real, and 14/20 is fine for v0.2.
- **Ruff `S` rules** (security) are mostly ignored per-file
  because they fire on intentional patterns. That's a v0.3
  decision: either rewrite the patterns or document why they're
  intentional in a `SECURITY.md`.

## Things I will NOT add

- Tool-calling. Once you let the LLM call tools, the post-
  inference security property is gone. If you want tool-calling,
  use OpenClaw or Hermes Agent. Don't add it to lever-runner.
- Multi-user trust without per-chat isolation. v0.2 ships that
  isolation, so this is now solved at the table level — but
  sharing a *chat* (group chat with a bot) still shares trust
  within that chat. If we ever want per-user trust in a group,
  that needs a different table layout (`commands_<chat>_<user>`).
- A "viral" marketing surface. The `web/index.html` is honest
  about what lever-runner is and isn't. Don't add the comparison
  table back as a marketing piece.
