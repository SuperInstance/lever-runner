# AGENTS.md — operating lever-runner

> Operator-focused notes for a future agent (or human) picking this codebase up cold. The README explains what it is; this file explains how to use it.

## TL;DR

```bash
# Run a command
.venv/bin/python -m lever_runner "check disk usage"

# Teach a new command
.venv/bin/python -m lever_runner teach "show my IP" | curl -s https://ifconfig.me

# See how many commands are loaded
.venv/bin/python -m lever_runner status

# Reset everything (drops the table, re-seeds 66 commands)
.venv/bin/python init_db.py --reset

# Run the smoke test (isolated tempdir, never touches live data)
.venv/bin/python -m tests.smoke

# Run the benchmark
.venv/bin/python -m lever_runner.benchmark

# Start the Telegram bot (foreground)
.venv/bin/python -m lever_runner.bot
```

## Layout

```
lever-runner/
├── init_db.py                  # seed pack + LanceDB table bootstrap
├── install.sh                  # one-shot installer (system deps, venv, systemd)
├── src/lever_runner/
│   ├── __init__.py             # __version__
│   ├── __main__.py             # `python -m lever_runner ...` -> cli.main
│   ├── cli.py                  # plain-text CLI dispatcher
│   ├── bot.py                  # Telegram adapter
│   ├── http_api.py             # stdlib HTTP server on :8765
│   ├── orchestrator.py         # the one true entry point: do/teach/status
│   ├── store.py                # LanceDB wrapper (lazy embedder, trust ops)
│   ├── intent_extractor.py     # 4-backend LLM client (passthrough/minimax/openai/ollama)
│   ├── executor.py             # sandboxed subprocess.run with timeout
│   ├── benchmark.py            # 20-task suite; forces LLM_BACKEND=passthrough
│   ├── auto_promote.py         # hourly cron job: promote winners, surface losers
│   └── token_logger.py         # JSONL append-only token/embed accounting
├── tests/
│   ├── __init__.py
│   └── smoke.py                # 18-check end-to-end test, isolated tempdir
├── systemd/
│   └── lever-runner-bot.service
├── README.md                   # user-facing overview, comparison table
└── AGENTS.md                   # this file
```

## Architecture, in one paragraph

`orchestrator.do(user_request)` is the single dispatcher. It calls `intent_extractor.extract()` to compress the user request into a 3–8 word phrase (no tool schema, no chain-of-thought, ~60 input tokens). It embeds the phrase with `all-MiniLM-L6-v2`, calls `store.find_best()` to get the top-3 cosine matches, picks the best-similarity match whose trust is above `MATCH_MIN_TRUST` (default 40), and calls `executor.run_command()` to run the pre-approved command in a per-session sandbox under `/tmp/lever-runner/<session_id>/`. After execution, `store.update_trust()` bumps +1.5 on success or -4.0 on failure. The CLI, Telegram bot, and HTTP API are all thin adapters over `orchestrator.do()`.

## What "the LLM never sees shell" means in practice

`intent_extractor.py` has a fixed system prompt that asks the LLM to compress a sentence into a phrase. The LLM is **not** given a tool schema, function-calling protocol, or any indication that phrases will be matched against commands. The LLM does not know that `df -h` is the answer to "check disk usage." That's the embedding model's job.

If `LLM_BACKEND=passthrough`, no LLM is called at all — the user request is normalized and used as the intent phrase verbatim. This is the cheapest mode and is what `benchmark.py` measures.

## Trust model

- `TRUST_NEW_COMMAND` (default 50): trust at which new commands start (from `/teach` or auto-promote rewrites)
- `MATCH_MIN_TRUST` (default 40, hardcoded): match selection ignores rows below this
- `TRUST_PROMOTE_FLOOR` (default 30): `auto_promote` considers rows below this as candidates for rewrite
- `TRUST_PROMOTE_FAILURES` (default 5): minimum failure_count to be considered for rewrite
- `TRUST_SUCCESS_BUMP_THRESHOLD` (default 20): success_count required for hourly +10 bump
- `TRUST_SUCCESS_BUMP_AMOUNT` (default 10): the +10 amount
- `TRUST_REWRITTEN_COMMAND` (default 40): trust at which `auto_promote` inserts rewrites
- `MATCH_SIMILARITY_FLOOR` (default 0.55): below this, the orchestrator returns `no_match=True` and surfaces `/teach` instead of running a low-confidence match

Trust is a **gate** on selection, not a tiebreaker for similar matches. The match with the lowest L2 distance wins among those above `MATCH_MIN_TRUST`. This is the fix for the original `max((trust, -distance))` inversion — see `tests/smoke.py` step 7 for the regression test.

## How to add a command

Three options, in order of preference:

1. **`/teach` (Telegram) or `teach` (CLI):** user-facing, instant, trust=50
2. **Edit `init_db.py` SEED_COMMANDS and re-seed with `python init_db.py --reset`:** for commands every install should have
3. **`auto_promote.py` rewrite path:** if `REMOTE_LLM_API_KEY` is set, the hourly cron can rewrite failing commands on its own. We do not recommend enabling this without a human in the loop — it tends to drift.

## How to extend the seed pack

1. Add `{intent, command}` entries to `SEED_COMMANDS` in `init_db.py`. Use 3–8 word intent phrases written the way a real user would type them.
2. Run `.venv/bin/python init_db.py --reset` to rebuild the table.
3. Smoke-test: `.venv/bin/python -m tests.smoke` should still pass.
4. Commit the change.

## Backends

| Backend | Set in `.env` | Notes |
|---|---|---|
| `passthrough` | `LLM_BACKEND=passthrough` | No LLM call; user request is the intent phrase verbatim. Cheapest, offline-capable. |
| `minimax` | `LLM_BACKEND=minimax` | Hosted MiniMax-M3 via Anthropic-compatible API. Reads key from env (`MINIMAX_API_KEY`, `ANTHROPIC_API_KEY`, or `LLM_API_KEY`). |
| `openai` | `LLM_BACKEND=openai` | Any OpenAI-compatible chat endpoint. |
| `ollama` | `LLM_BACKEND=ollama` | Local Ollama. `ollama pull llama3.1:8b-instruct-q4_K_M` first. |

The default in `.env.example` is `passthrough`. Switch to `minimax` once `MINIMAX_API_KEY` is in your process env.

## Cron setup (optional)

```bash
# Run the hourly self-improvement loop
0 * * * *  cd /home/ubuntu/lever-runner && .venv/bin/python -m lever_runner.auto_promote >> logs/auto_promote.log 2>&1
```

The loop is a no-op if no rows are below the failure threshold and no `REMOTE_LLM_API_KEY` is set. Safe to leave running.

## Secrets

- `TELEGRAM_BOT_TOKEN` is required to start the bot. Read from `.env` (gitignored) by `bot.py`.
- `MINIMAX_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` are read from the process environment, not `.env` — so they can be set in `/etc/environment` or your shell rc and the `.env` file remains safe to share.
- `REMOTE_LLM_API_KEY` is read from env by `auto_promote.py`. Same reasoning.

`.env` is in `.gitignore`. Verify with `git check-ignore -v .env` — should print the gitignore rule.

## Known gotchas

- **LanceDB read-after-write**: solved with `read_consistency_interval=0` in `store.py`. If you see "freshly-taught command not findable on next `/do`," that's regressed.
- **Python 3.14 + torch 2.12 + lancedb 0.33** is bleeding edge and works on this Oracle ARM box. If you see `lancedb.connect()` rejecting `read_consistency_interval` as a float, you need a `timedelta` — the import handles that.
- **The benchmark forces `passthrough`** (sets `LLM_BACKEND=passthrough` in the script). Don't read 6.3 tokens/cmd as the production number; with a hosted LLM it's ~70-90. The < 200 target still holds.
- **Telegram bot token rotation**: if your token has been visible in any untrusted context (screen-share, log file, agent context), rotate it via @BotFather and update `.env`.

## What is intentionally NOT here

- No HTTP auth on `http_api.py` — assumes the loopback interface or a trusted network. Add a token check before exposing.
- No prompt-injection guardrails on the LLM backend. The threat model is "the LLM can only output a phrase; the phrase is matched against a fixed table; the LLM cannot inject shell." That's the design. If you let the LLM also call tools, you've lost the security property.
- No multi-user trust isolation. The trust score is global, not per-user.
- No undo for `/teach`. You can `delete_command` rows by id, but there is no command-line undo.
