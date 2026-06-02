# TODO — what I'd want for v0.2

A list of things I noticed during the v0.1.0 / v0.1.1 build but
deliberately didn't do. Not a roadmap — just a place to put the
"if I had more time" notes so they don't get lost.

## Correctness / robustness

- **Trust-dynamics tests for `auto_promote.py`.** The smoke test
  exercises `tests/smoke.py` end-to-end but doesn't touch the cron
  path. Specifically: insert a row, give it 21 successes, run
  `auto_promote`, verify trust is bumped +10. Insert a row, give
  it 6 failures, run, verify it's surfaced as a candidate (and
  that without `REMOTE_LLM_API_KEY` nothing is rewritten).
- **Race-condition test for read-after-write.** We saw the
  LanceDB read-after-write race during the v0.1.0 build (teach +
  immediate do returned the wrong row). The fix was
  `read_consistency_interval=0`, but the test would need to
  reproduce the race deterministically, which is hard. Worth
  trying.
- **Concurrent `/teach` from multiple chat IDs.** Right now there's
  one global trust table. Two users with different intents could
  race on `update_trust` writes via lancedb's append semantics.
  Low priority — lancedb is fine with concurrent reads + serialized
  writes, and there's only one user (Casey) right now.
- **Token budget on the LLM call.** `intent_extractor` doesn't
  enforce a max output token count or a request timeout. If the
  LLM hangs, `/do` hangs. Add a 5s timeout.

## Operational

- **`pyproject.toml` `setup.cfg`-style entry point** so the
  package installs without the editable hack. The current
  `package-dir = {"" = "src"}` works but isn't idiomatic.
- **Log rotation.** `logs/bot.log`, `logs/token_usage.jsonl`, and
  `logs/auto_promote.log` grow forever. Add a daily logrotate
  config.
- **Health endpoint on `http_api.py`.** Right now the only HTTP
  surface is `/run` and `/teach`. Add `GET /health` that returns
  JSON with `version`, `command_count`, `uptime_seconds`.
- **Per-chat trust.** The trust score is global, not per-user.
  If you ever share the bot, you want the trust score to be
  per-chat so Casey's "df -h is good" doesn't propagate to a
  stranger's "rm -rf is good."
- **Secret rotation helper.** A `make rotate-telegram-token` that
  walks you through @BotFather, then updates `.env` and restarts
  the systemd unit. Or just: rotate the four exposed keys
  (Telegram, MINIMAX, DEEPINFRA, ZAI) manually.

## Features

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
  page; an actual SPA-ish thing. v0.2+ at earliest.

## Code quality

- **`bot.py` test coverage.** The handlers are all unit-testable
  with a mock `Update` object. There are zero tests for `bot.py`
  today.
- **`intent_extractor.py` test coverage.** The 4 backends should
  each have a happy-path test and a "backend down" test.
- **The benchmark's pass count is 14/20** which is honest but
  low. Add more seeds or relax the similarity floor — but the
  trade-off is real, and 14/20 is fine for a v0.1.
- **Ruff `S` rules** (security) are mostly ignored per-file
  because they fire on intentional patterns. That's a v0.2
  decision: either rewrite the patterns or document why they're
  intentional in a `SECURITY.md`.

## Things I will NOT add

- Tool-calling. Once you let the LLM call tools, the post-
  inference security property is gone. If you want tool-calling,
  use OpenClaw or Hermes Agent. Don't add it to lever-runner.
- Multi-user trust without per-chat isolation. Sharing a global
  trust table is the foot-gun.
- A "viral" marketing surface. The `web/index.html` is honest
  about what lever-runner is and isn't. Don't add the comparison
  table back as a marketing piece.
