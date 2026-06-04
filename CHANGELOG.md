# Changelog

All notable changes to lever-runner are documented here.

## v1.0.0 — First Public Release (2026-06-03)

The first stable release. Post-inference command execution where the LLM never sees your shell.

### Core Features

- **Post-inference architecture.** The LLM produces a 3-8 word intent phrase; lever-runner matches it to a pre-approved command in a LanceDB table. The model never sees tool schemas, shell syntax, or your filesystem.
- **Token-lean execution.** ~70-90 tokens per command with a hosted LLM, ~6 tokens with passthrough mode. Traditional tool-calling agents spend 1,500-8,000 tokens per turn.
- **Three-gate security.** Rust fastloop-guard (~50µs) → Python cache (~200µs, 44% hit rate) → LLM fallback (~500ms). Every command is pre-approved, trust-scored, and sandboxed.
- **Parameterized commands.** Teach templates with `{{param}}` slots: `docker logs --tail 100 {{container}}`. Arguments are validated at execution time — shell metacharacters are blocked.
- **Trust scoring.** Every execution updates a trust score. Successful runs promote; failures demote. Commands below the trust floor require confirmation.
- **Per-session sandbox.** Each execution runs in `/tmp/lever-runner/<session_id>/` with a hard timeout (default 30s).
- **Multiple backends.** Ollama (local), OpenAI, DeepInfra, Minimax, or passthrough (zero API keys, $0/month). Fallback chain degrades gracefully to passthrough on provider outage.

### Skill Packs

- **77 built-in seed commands** covering system administration, Docker, git, networking, and file management.
- **45-command DevOps skill pack.** Kubernetes, Terraform, systemd, nginx, Redis, PostgreSQL, and more.
- **32-command git skill pack.** Branching, rebasing, stash workflows, conflict resolution, bisect, and blame.
- **Import/export.** Share command sets as `.jsonl` files. Build a library of community skill packs.

### Integrations

- **pincherOS `.nail` export.** Export your taught commands as pincherOS reflex files for device migration and offline caching. The `.nail` file is a tar.zst archive with embedded vectors for instant similarity search.
- **Three-gate fastloop bridge.** Rust `fastloop-guard` daemon provides ~50µs matching via Unix domain sockets, with automatic Python fallback.
- **HTTP API.** `POST /run` for programmatic access. `GET /healthz` for monitoring.
- **Telegram bot.** `/do`, `/teach`, `/status`, `/commands`, `/stats` — full conversational interface.
- **CLI.** `python -m lever_runner "check disk usage"` — zero-config command execution.

### Browser & Web

- **Pyodide browser demo.** Zero-server, zero-API-key demo that runs entirely in the browser. Open `browser/index.html` and go.
- **Gradio web UI.** `pip install lever-runner[web]` for a full web interface with Gradio.
- **Docker container.** `Dockerfile.web` for containerized web deployment (Codespaces, Fly.io, etc.).

### Benchmarks (RTX 4050)

- Vector search: 7.6ms p50, 15.2ms p99
- Teach throughput: 122 commands/sec
- GPU embedding: 2.6ms per intent
- Template match: 1.7µs (CPU only)
- Fastloop guard (Rust): ~50µs per lookup

### Experimental Foundation

This project builds on research from the [zeroclaw-arena](https://github.com/SuperInstance/zeroclaw-arena) project, which proved that vector-DB-based strategy learning works without neural networks. The tile field compiler innovations (96.5% dead code elimination, rank-1 SVD compression, hierarchical tiles) informed lever-runner's three-gate architecture.

Related experimental projects:
- **zeroclaw-arena** — Game-learning agents proving the vector-DB strategy thesis
- **pincherOS** — Rust agent runtime with reflex caching and `.nail` migration
- **tile-compiler** — Strategy compilation pipeline (train → compile → deploy)
- **superinstance-ecosystem** — Four-layer agent architecture research

### Contributors

Built by the SuperInstance collective: Forgemaster (RTX 4050 + Ryzen 9 5900X) and Loom (ARM64 edge).

---

## v0.4.0 — PyPI Prep

- Browser strategy analysis and Pyodide demo
- Container-based browser deployment configs
- Three-gate architecture integration tests
- Fastloop-guard Rust bridge with Python fallback
- Neural embedder v2 (60% top-1 with scaled training)
- `.nail` export schema aligned with pincherOS

## v0.3.1 — More Bot Commands

- `/commands [N] [--page=K]` — paginated command listing
- `/stats <phrase>` — full command statistics
- `/teach --trust=N` — override starting trust
- `store.list_all()` and `store.get_by_id()` — store API
- Pandas added as explicit dependency

## v0.3.0 — DeepInfra Backend, Provider Fallback Chain

- Provider fallback chain (`LLM_FALLBACKS` env var)
- DeepInfra backend with Meta-Llama-3.1-8B-Instruct
- Per-backend URL/model environment variables
- Graceful degradation to passthrough on provider outage

## v0.2.x — Per-Chat Isolation, Timeouts, Healthz

- Per-chat trust isolation via separate LanceDB tables
- LLM request timeout (`LLM_TIMEOUT_SEC`)
- Log rotation (5 MiB with 3 backups)
- `/healthz` endpoint for monitoring

## v0.1.x — Initial Release

Telegram bot, LanceDB store, embedding pipeline, 66-command seed pack, hourly self-improvement loop, installable package, 6 console scripts, pre-commit + CI.
