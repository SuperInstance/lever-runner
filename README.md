# Lever-Runner

> **Post-inference command execution. The LLM never sees your shell.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![Vector DB: LanceDB](https://img.shields.io/badge/vector-LanceDB-green.svg)]()

A self-improving, token-lean AI command executor. You send natural language;
Lever-Runner returns a pre-approved shell command and runs it. The local LLM
only ever sees a short *intent phrase* — never tool schemas, never raw shell.

```
You:   "check disk usage on the server"
LLM:   intent = "show disk usage"
Embed: [0.02, -0.18, 0.44, ...]
Find:  df -h
Run:   $ df -h
```

That's it. No JSON tool calls, no MCP, no function-calling protocol. The
expensive model is asked to do one cheap thing well: turn a sentence into a
phrase.

---

## Why it exists

Tool-calling agents (OpenClaw, Hermes Agent, LangChain ReAct, etc.) ship the
entire tool schema into the prompt on every turn. A few dozen tools = a few
thousand tokens of overhead **per inference**, and the model still has to
synthesize a correct shell command from scratch. The blast radius is also bad:
a hallucinated `rm -rf` is one prompt-injection away.

Lever-Runner inverts the architecture:

| Step | Traditional RAG / Tool-calling | Lever-Runner |
|------|--------------------------------|--------------|
| 1 | Stuff tool schemas into prompt | Send a few-line prompt asking for an *intent phrase* |
| 2 | LLM generates a JSON tool call | LLM returns a 3-8 word phrase |
| 3 | Parse JSON, validate args | Embed phrase, cosine-search a LanceDB table |
| 4 | Execute the tool | Execute the matched **pre-approved** command |
| 5 | Hope it was safe | Trust score + sandbox + timeout |

The LLM never has the power to invent a destructive command. The blast radius
of a hostile prompt is "the wrong command ran once, and we noted it in the
trust score." A community-vetted command table does the rest.

## Headline numbers

- **< 200 tokens** per executed command (target). Real tool-calling agents
  routinely spend 1,500–8,000 tokens of prompt overhead before the user is even
  considered.
- **24 GB RAM** is enough. `all-MiniLM-L6-v2` is ~80 MB; `llama3.1:8b-instruct-q4_K_M`
  fits comfortably alongside it.
- **$0/month** on Oracle Cloud Free Tier. Local LLM, embedded DB, no API
  required for the hot path.

## How it works (the loop)

```
user request
     │
     ▼
┌──────────────┐
│ local LLM    │  →  "show disk usage"           (≈ 60 tok in / 8 tok out)
└──────────────┘
     │ intent phrase
     ▼
┌──────────────┐
│ MiniLM embed │  →  384-dim vector              (≈ 12 tok equivalent)
└──────────────┘
     │
     ▼
┌──────────────┐
│ LanceDB      │  →  top-1 command: "df -h"
└──────────────┘
     │
     ▼
┌──────────────┐
│ sandbox exec │  →  /tmp/lever-runner/<sid>/, timeout, capture stdout/stderr
└──────────────┘
     │
     ▼
trust += success ? +Δ : -Δ,  log everything
```

A cron job runs `auto_promote.py` every hour. Commands that fail 5+ times with
trust < 30 get sent to a stronger remote LLM (Claude 3.5 Sonnet by default)
to be rewritten, and the new version is inserted at trust 40. Commands that
succeed 20+ times climb toward 90 and become "trusted" — they're picked
preferentially even when other matches exist.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/SuperInstance/lever-runner/main/install.sh | bash
```

The installer pulls Python deps, asks you to start Ollama, pulls
`llama3.1:8b-instruct-q4_K_M`, downloads the `all-MiniLM-L6-v2` embedding
model, seeds the database, and starts the Telegram bot. See `install.sh` for
the exact steps.

## Usage

### Telegram

```
/do check disk usage
/teach "show docker containers" | docker ps --format 'table {{.Names}}\t{{.Status}}'
/status
```

### CLI

```bash
python -m lever_runner "check disk usage"
```

### JSON API

```bash
curl -X POST http://localhost:8765/run -d '{"request": "restart nginx"}' -H 'content-type: application/json'
```

## Comparison: Lever-Runner vs. Tool-calling Agents

| | **Lever-Runner** | **OpenClaw / Hermes Agent** | **LangChain ReAct** |
|---|---|---|---|
| Token cost / turn | **< 200** | 1,500 – 8,000 | 2,000 – 10,000 |
| LLM sees shell? | **No** | Yes (via tool schema) | Yes |
| Prompt-injection blast radius | Low (no shell synthesis) | High | High |
| Adds a new capability | `/teach` in Telegram (1 message) | Edit code, redeploy | Edit code, redeploy |
| Self-improves | Yes (auto_promote.py) | No (out of band) | No (out of band) |
| Offline-capable | **Yes** | Partially | No (usually) |
| Min. RAM | **4 GB** | 8 GB + remote calls | 8 GB + remote calls |
| Cloud bill | **$0** | $5 – $50+/mo | $20 – $200+/mo |

## Community Skills

Got a command set that's useful? Export your database:

```bash
python -m lever_runner.export > my-skillpack.jsonl
```

Import someone else's:

```bash
python -m lever_runner.import awesome-skillpack.jsonl
```

We're building a public skill library at
[SuperInstance/lever-runner-skills](https://github.com/SuperInstance/lever-runner-skills)
(coming soon). Submit a PR with your `.jsonl` and a one-paragraph
description of what it does.

## Architecture in one paragraph

`orchestrator.py` handles inbound messages (Telegram / CLI / HTTP), calls the
local Ollama model to extract a short intent, embeds the intent with
`all-MiniLM-L6-v2`, queries a LanceDB table of `{intent_phrase, command,
trust_score, success_count, failure_count, embedding}` rows, picks the
top-confidence entry above a trust floor, runs the command in a per-session
sandbox under `/tmp/lever-runner/<session_id>/` with a hard timeout, and
updates the trust score. `init_db.py` creates the table and seeds it with 50
common commands. `auto_promote.py` runs hourly: it demotes/rewrites failing
commands and promotes reliable ones. The LLM is intentionally *not* in the
hot path for command selection — it's only there to compress a sentence into
a phrase.

## Security model

- **LLM can never invent a shell command.** It only emits a phrase; the
  command is always looked up from the pre-approved table.
- **Per-session sandbox.** Every execution lives in
  `/tmp/lever-runner/<session_id>/` and is wiped on session end.
- **Hard timeout.** `COMMAND_TIMEOUT_SEC` (default 30s) kills runaway
  processes.
- **Trust gating.** Below a configurable floor, low-trust commands are not
  auto-executed — the user gets a confirmation prompt.
- **No secrets in prompts.** The LLM never sees API keys, paths to credentials,
  or environment variables. The `.env` file is loaded only in the executor
  layer.

## License

MIT. See [LICENSE](LICENSE).

## Status

**v0.1.0** — initial release. Telegram bot, LanceDB store, embedding pipeline,
50-command seed pack, hourly self-improvement loop, token benchmark.
