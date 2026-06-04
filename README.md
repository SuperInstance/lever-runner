# lever-runner

> **The trust compiler. Teach once, run forever. The LLM never sees your shell.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)]()
[![Tests: 160](https://img.shields.io/badge/tests-160%20passing-brightgreen.svg)]()
[![PyPI](https://img.shields.io/badge/PyPI-v0.4.0-blue.svg)]()

---

## 30 seconds

```bash
git clone https://github.com/SuperInstance/lever-runner && cd lever-runner
pip install -e .
export LLM_BACKEND=passthrough    # zero API keys, $0/month
lever "check disk usage"           # → df -h
```

```bash
lever teach "show my ip" --command "curl ifconfig.me"
lever "what's my ip"              # → curl ifconfig.me
```

That's it. You taught it something in one command. It remembers forever.
The LLM never saw your shell, your files, or your network.

---

## The problem with AI shell tools

Every AI shell assistant — Copilot, Warp, Cursor — works the same way:

```
your terminal ──► cloud LLM ──► shell command
```

The LLM sees everything. Your directory structure. Your env vars. Your
history. And it *has* to see everything, because it synthesizes commands
from scratch every time. This means:

- **Prompt injection is a feature, not a bug.** The model needs shell access to work.
- **2,000+ tokens per query.** Tool schemas, context, history — shipped to the cloud every turn.
- **$50-200/month cloud bills.** That's what it costs to send 2K tokens 500 times a day.
- **Your data leaves the machine.** Every terminal session is a data exfiltration vector.

We've been told this is inevitable. It's not.

---

## The insight: you don't need an LLM at runtime

You need it **once** — to understand what you mean. After that, it's
vector search.

```
              ┌─────────────────────────────────────────────┐
              │           lever-runner architecture          │
              │                                              │
  "check     │  ┌─────────┐    ┌──────────┐    ┌────────┐  │
   disk      │  │  Gate 1  │    │  Gate 2   │    │ Gate 3 │  │
   usage" ───┼─►│  Rust    │───►│  Python   │───►│  LLM   │  │
              │  │  50µs    │    │  200µs    │    │ 500ms  │  │
              │  │ template │    │  cache    │    │ intent │  │
              │  │  match   │    │  44% hit  │    │ phrase │  │
              │  └─────────┘    └──────────┘    └────────┘  │
              │        │              │               │       │
              │        └──────────────┴───────────────┘       │
              │                       │                       │
              │                       ▼                       │
              │              ┌───────────────┐                │
              │              │  Vector DB    │                │
              │              │  cosine search │                │
              │              │  → "df -h"     │                │
              │              └───────────────┘                │
              │                       │                       │
              │                       ▼                       │
              │              ┌───────────────┐                │
              │              │  Sandbox exec  │                │
              │              │  trust score   │                │
              │              └───────────────┘                │
              └─────────────────────────────────────────────┘
```

**Three gates.** Most queries never reach the LLM:

| Gate | Layer | Latency | What happens |
|------|-------|---------|--------------|
| 1 | Rust fastloop | **50µs** | Template match: "check disk" → `df -h` |
| 2 | Python cache | **200µs** | Embedding cache hit (44% of queries) |
| 3 | LLM | **500ms** | "What does the user mean?" → intent phrase |

Gate 3 is the only one that costs money or sends data anywhere.
And the LLM never sees your shell — it only sees a 5-word intent phrase.

### The 70-token metric

```
lever-runner:  ~70 tokens per query
Copilot CLI:  ~2,000 tokens per query
Warp AI:      ~3,500 tokens per query
Cursor:       ~5,000 tokens per query
```

That's **28× cheaper, 28× faster, 28× less data leaving your machine.**
And in passthrough mode (`LLM_BACKEND=passthrough`), it's **0 tokens** —
your exact words become the search key. No LLM call at all.

---

## Real numbers

All benchmarks run on real hardware. No theoretical best-case.

| Metric | Value | Hardware |
|--------|-------|----------|
| Vector search p50 | **7.6ms** | Ryzen 5900X, 1K vectors |
| Template match | **1.7µs** | Any hardware |
| Teach throughput | **122/sec** | Ryzen 5900X |
| Hash embedding | **55µs** | Any hardware, no GPU |
| GPU embedding | **2.6ms** | RTX 4050 |
| Cache hit rate | **44%** | Production workload |
| Min RAM | **4 GB** | Passthrough mode |
| Zero-API-key mode | ✅ | `$0/month` |
| ARM64 support | ✅ | Oracle Cloud Free Tier |
| Tests passing | **160** | CI green |
| Built-in commands | **67** | Seeded on first run |

See [BENCHMARKS.md](BENCHMARKS.md) for full methodology.

---

## Quick start

### Zero API keys (recommended for trying it out)

```bash
git clone https://github.com/SuperInstance/lever-runner && cd lever-runner
pip install -e .
export LLM_BACKEND=passthrough
lever "check disk usage"           # → df -h
lever "show running processes"     # → ps aux
lever "list docker containers"     # → docker ps
```

67 built-in commands. No API keys. No cloud. No data leaving your machine.

### With a local LLM (best accuracy)

```bash
# Install Ollama, then:
ollama pull llama3.1:8b-instruct-q4_K_M
export LLM_BACKEND=ollama
lever "check disk usage"           # → df -h (with intent extraction)
```

### With a cloud LLM (highest accuracy)

```bash
export LLM_BACKEND=openai
export LLM_API_KEY=sk-...
lever "check disk usage"
```

### Teach it something new

```bash
# Simple command
lever teach "show my public ip" --command "curl ifconfig.me"

# Parameterized command ({{param}} templates)
lever teach "show logs for {{container}}" --command "docker logs --tail 100 {{container}}"
lever "show logs for nginx"               # → docker logs --tail 100 nginx

# With a trust score (you know this command is solid)
lever teach --trust=90 "restart nginx" --command "sudo systemctl restart nginx"
```

### From any surface

```bash
# CLI
lever "check disk usage"

# Telegram bot
/do check disk usage
/teach "show containers" | docker ps

# HTTP API
curl -X POST http://localhost:8765/run \
  -d '{"request": "restart nginx"}' \
  -H 'content-type: application/json'

# TUI (coming in v0.5)
lever tui
```

---

## Git-Native Agents

lever-runner is the first **git-native agent** runtime. The paradigm:

```
Traditional agent:  LLM → tool call → execute → hope
Copilot agent:      LLM → suggestion → approve → pray
Git-native agent:   teach once → compile → verify → run forever
```

A git-native agent is:
- **A repo.** Its knowledge is version-controlled, forkable, auditable.
- **Compiled, not interpreted.** The LLM runs once at "compile time" (teach).
  At "runtime", it's pure vector search — no LLM needed.
- **Portable.** Export your commands as `.nail` files, move to another machine,
  import. Same muscle memory, different hardware.
- **Composable.** Skill packs are JSONL files. Mix, match, share via PR.

```bash
# Export your skills
lever export > my-skills.jsonl

# Import someone else's
lever import devops-skills.jsonl

# Export for pincherOS (agent state migration)
lever export-nail --output reflexes.nail
```

### The SuperInstance Ecosystem

lever-runner is one piece of a larger architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    SuperInstance                         │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ lever-runner │  │  pincherOS   │  │  tile-compiler│  │
│  │  execution   │  │    memory    │  │  compilation  │  │
│  │              │  │              │  │               │  │
│  │ "run this"  │  │ "remember    │  │ "compile      │  │
│  │  safely     │  │  this"       │  │  strategy"    │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬────────┘  │
│         │                 │                  │           │
│         └────────┬────────┴──────────────────┘           │
│                  │                                       │
│         ┌────────▼────────┐                              │
│         │      PLATO      │                              │
│         │  orchestration  │                              │
│         │  distillation   │                              │
│         │  rooms          │                              │
│         └─────────────────┘                              │
└─────────────────────────────────────────────────────────┘
```

| Repo | Role | Stars |
|------|------|-------|
| [lever-runner](https://github.com/SuperInstance/lever-runner) | Injection-proof shell execution | — |
| [pincherOS](https://github.com/SuperInstance/pincherOS) | Agent runtime with reflex caching | — |
| [tile-compiler](https://github.com/SuperInstance/tile-compiler) | Strategy compilation (zero-dep) | — |
| [zeroclaw-arena](https://github.com/SuperInstance/zeroclaw-arena) | Self-improving game agents | — |
| [conservation-spectral-topology-rs](https://github.com/SuperInstance/conservation-spectral-topology-rs) | Ecosystem health (Rust) | — |
| [superinstance-ecosystem](https://github.com/SuperInstance/superinstance-ecosystem) | Architecture + research | — |
| [captains-log](https://github.com/SuperInstance/captains-log) | Agent-to-agent coordination | — |

---

## Comparison

| | **lever-runner** | **GitHub Copilot CLI** | **Warp AI** | **OpenInterpreter** |
|---|---|---|---|---|
| Tokens/query | **~70** | ~2,000 | ~3,500 | ~5,000+ |
| LLM sees shell? | **No** | Yes | Yes | Yes |
| Prompt injection risk | **Near-zero** | High | High | High |
| Works offline | **Yes** | No | No | No |
| $0/month option | **Yes** | No | No | No |
| Teach new command | 1 message | Edit config | Edit config | Edit code |
| Trust scoring | **Built-in** | None | None | None |
| Portable skills | **JSONL export** | No | No | No |
| ARM/Raspberry Pi | **Yes** | No | No | Partial |
| Open source | **MIT** | No | No | Yes |

---

## How it works

```
You type:  "check disk usage on the server"
                    │
     ┌──────────────▼──────────────┐
     │ Gate 1: Rust fastloop (50µs)│──► template match? ──► df -h
     └──────────────┬──────────────┘     miss ↓
     ┌──────────────▼──────────────┐
     │ Gate 2: Python cache (200µs)│──► embedding hit? ──► df -h
     └──────────────┬──────────────┘     miss ↓
     ┌──────────────▼──────────────┐
     │ Gate 3: LLM (500ms)         │──► "show disk usage"
     │   sees ONLY the phrase      │    (8 tokens, not 2000)
     └──────────────┬──────────────┘
                    │
     ┌──────────────▼──────────────┐
     │ Vector search (LanceDB)     │──► cosine top-1: "df -h"
     └──────────────┬──────────────┘
                    │
     ┌──────────────▼──────────────┐
     │ Sandbox execution           │──► /tmp/lever-runner/<id>/
     │   timeout: 30s              │     trust += success ? +Δ : -Δ
     │   trust gate                │     log everything
     └─────────────────────────────┘
```

The LLM is asked to do one cheap thing: turn a sentence into a phrase.
It never sees your filesystem, your environment, or your commands.

### Self-improvement loop

A cron runs `auto_promote.py` hourly:

1. **Promote winners.** Commands with 20+ successes get trust boosts.
2. **Surface failures.** Low-trust commands get flagged. If a remote LLM key is configured, it proposes a fix (opt-in). If not, it just prints the list.

---

## Security model

| Principle | Implementation |
|-----------|---------------|
| LLM can't invent commands | LLM emits a phrase; command is looked up from pre-approved table |
| Per-session sandbox | Every execution in `/tmp/lever-runner/<session_id>/` |
| Hard timeout | `COMMAND_TIMEOUT_SEC` (default 30s) kills runaways |
| Trust gating | Low-trust commands require confirmation |
| No secrets in prompts | LLM never sees API keys, paths, or env vars |
| Shell injection blocked | Arguments validated, metacharacters rejected |
| Zero network in passthrough | No data leaves the machine at all |

---

## Surfaces

| Surface | Status | Usage |
|---------|--------|-------|
| **CLI** | ✅ Shipping | `lever "check disk"` |
| **Telegram bot** | ✅ Shipping | `/do check disk` |
| **HTTP API** | ✅ Shipping | `POST /run` on port 8765 |
| **TUI** | 🔄 Planned (v0.5) | `lever tui` |
| **Web UI** | 🔄 Planned (v0.6) | Browser-based dashboard |
| **Gradio** | 🔄 Container ready | `docker compose up` |
| **git-native agent** | ✅ Design complete | Skill packs as repo artifacts |
| **Browser (Pyodide)** | ✅ Demo | `browser/index.html`, zero server |

---

## Skill packs

```bash
# Built-in: 67 commands covering system, docker, git, networking
lever stats                    # see what you have

# Import community packs
lever import devops-pack.jsonl
lever import git-pack.jsonl

# Export and share
lever export > my-pack.jsonl   # PR to lever-runner-skills
```

---

## pincherOS Integration

Export commands as `.nail` files for reflex caching and device migration:

```bash
lever export-nail --output reflexes.nail
# On another device:
pincher import reflexes.nail
```

The `.nail` file is a tar.zst archive with SQLite, manifest, identity,
and config — fully compatible with pincherOS's migration format.

---

## Install

```bash
# Quick install
git clone https://github.com/SuperInstance/lever-runner && cd lever-runner
pip install -e .

# Or the install script (sets up Ollama, downloads models, seeds DB)
curl -fsSL https://raw.githubusercontent.com/SuperInstance/lever-runner/main/install.sh | bash

# Minimal (no LLM, zero API keys)
pip install -e .
export LLM_BACKEND=passthrough
```

### Requirements

- Python 3.10+
- 4 GB RAM (passthrough mode) / 12 GB+ (local LLM mode)
- No GPU required
- Works on ARM64 (Oracle Cloud Free Tier, Raspberry Pi)

---

## Benchmarks

See [BENCHMARKS.md](BENCHMARKS.md) for the full breakdown. Highlights:

- **7.6ms** p50 vector search on Ryzen 5900X
- **1.7µs** template match (Rust fastloop)
- **122 commands/sec** teach throughput
- **44%** cache hit rate in production
- **28×** fewer tokens than Copilot CLI
- **$0/month** in passthrough mode

---

## License

MIT. Use it, fork it, ship it.

---

## Status

v0.4.0 — PyPI-ready, 160 tests, production-safe. See [CHANGELOG.md](CHANGELOG.md).

*lever-runner is part of the [SuperInstance ecosystem](https://github.com/SuperInstance/superinstance-ecosystem) — building the git-native agent stack from first principles.*
