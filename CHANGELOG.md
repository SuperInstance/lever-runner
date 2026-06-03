# Changelog

## v0.3.1 — more bot commands, full table introspection

- **`/commands [N] [--page=K]`** — list the commands in the current
  chat's table, sorted by trust desc. Default 20 per page, max 100.
- **`/stats <phrase>`** — full stats for one command: phrase,
  command, trust, success/failure counts, created/last_run
  timestamps, embedding distance/similarity, id. Respects
  `MATCH_SIMILARITY_FLOOR` — a phrase with no close match returns
  "no match" plus the top similarity for context.
- **`/teach --trust=N` flag** — override the starting trust when
  teaching a new command. Useful for "I know this command is
  solid, start it at 80" or "this came from a less-trusted
  source, start at 30". Also works in the CLI:
  `python -m lever_runner teach --trust=80 "phrase" | cmd`.
- **`store.list_all(...)`** — new method on `CommandStore` for
  paginated listing, with `limit`, `offset`, `min_trust` knobs.
  Used by `orchestrator.list_commands()` and the bot handler.
- **`store.get_by_id(row_id)`** — fetch a single row with full
  metadata (last_run, last_result, created_at, etc.). Used by
  `/stats` to pull everything we have on a command.
- **Pandas added to `requirements.txt`** — lancedb's `.to_pandas()`
  was a transitive dep, but newer lancedb versions don't declare
  it as a hard requirement, so the smoke test for `/commands`
  could fail in fresh envs. Declared explicitly.

## v0.3.0 — DeepInfra backend, provider fallback chain

- **Provider fallback chain (v0.3).** `LLM_FALLBACKS` env var
  (default `deepinfra`) sets a comma-separated list of backends
  tried in order when the primary errors. Retryable conditions:
  timeout, connection refused, 429, 5xx, 502, 503, 504, 529. 401
  also falls through to the next backend (bad key for one
  provider shouldn't break the whole chain). 4xx other than 401
  propagate up — those are config bugs that would fail the same
  way on any provider. The chain always ends at `passthrough` so
  a complete provider outage degrades to using the raw user
  request as the intent rather than hanging.
- **DeepInfra backend (v0.3).** `LLM_BACKEND=deepinfra` now works
  out of the box. Default model is
  `meta-llama/Meta-Llama-3.1-8B-Instruct` ($0.02/M input, $0.03/M
  output, 128K context). Key resolution:
  `LLM_API_KEY` first, then `DEEPINFRA_API_KEY`, then
  `DEEPINFRA_KEY` (first non-empty wins; not concatenated).
- **Per-backend URL/model env vars (v0.3).**
  `LLM_MINIMAX_BASE_URL`, `LLM_DEEPINFRA_BASE_URL`,
  `LLM_OPENAI_BASE_URL`, etc., let the operator override one
  backend's endpoint without leaking the global `LLM_BASE_URL`
  into fallback attempts.

## v0.2.x — per-chat isolation, LLM request timeout, log rotation, /healthz

- **Per-chat trust isolation (v0.2).** Each Telegram chat (or any client
  passing a `chat_id`) gets its own LanceDB table
  (`commands_<sanitized_chat_id>`). A `/teach` in chat A is invisible to
  chat B. New chats auto-seed with the global pack on first use.
- **LLM request timeout (v0.2).** `LLM_TIMEOUT_SEC` (default 5 s) covers
  connect + read. A timed-out request falls back to passthrough for that
  call.
- **Log rotation (v0.2).** `token_usage.jsonl` and `embed_usage.jsonl`
  rotate at 5 MiB with up to 3 backups (~20 MiB cap per log).
- **`/healthz` endpoint (v0.2).** `GET /healthz` returns `{ok, version,
  uptime_sec, tables, total_commands, lancedb_path}`.

## v0.1.x — initial release

Telegram bot, LanceDB store, embedding pipeline, 66-command seed pack,
hourly self-improvement loop (promote + optional rewrite), token benchmark,
installable package, 6 console scripts, pre-commit + CI.
