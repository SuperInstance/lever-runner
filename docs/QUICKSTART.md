# Quickstart Guide

Get from zero to executing commands in under 5 minutes. No API keys needed.

## Installation

### Option 1: pip (recommended)

```bash
pip install lever-runner
```

### Option 2: Docker

```bash
docker pull superinstance/lever-runner:latest
docker run -it superinstance/lever-runner "check disk usage"
```

### Option 3: From source

```bash
git clone https://github.com/SuperInstance/lever-runner && cd lever-runner
pip install -e .
```

### Option 4: Browser (zero install)

Open [browser/index.html](../browser/index.html) in any modern browser. Runs entirely client-side via Pyodide — no server, no API keys, nothing to install.

## First Run — Passthrough Mode

Passthrough mode uses your exact words as the intent. No LLM, no API keys, $0/month.

```bash
export LLM_BACKEND=passthrough
python -m lever_runner "check disk usage"
# → runs: df -h
```

That's it. 77 built-in commands covering system administration, Docker, git, networking, and file management. All pre-approved, all trust-scored.

Try a few more:

```bash
python -m lever_runner "list running processes"
# → runs: ps aux

python -m lever_runner "show memory usage"
# → runs: free -h

python -m lever_runner "what's my ip"
# → runs: curl -s ifconfig.me
```

## Teaching Commands

Teach lever-runner a new command in one line:

```bash
python -m lever_runner teach "show docker containers" --command "docker ps"
python -m lever_runner "show running containers"
# → runs: docker ps
```

It remembers forever. Teach it synonyms:

```bash
python -m lever_runner teach "list docker images" --command "docker images"
python -m lever_runner "what images do I have"
# → runs: docker images
```

The embedding model handles synonyms automatically — you don't need to teach every variation.

## Connecting to an LLM

Passthrough mode works, but an LLM makes it smarter. It compresses your sentence into a short intent phrase before matching, which improves accuracy on complex requests.

### Ollama (local, free)

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b-instruct-q4_K_M

# Configure lever-runner
export LLM_BACKEND=ollama
python -m lever_runner "how much space is left on the disk"
# → LLM extracts "show disk usage" → matches df -h → runs df -h
```

**Requirements:** 12 GB+ RAM for the 8B model. Works offline.

### OpenAI (cloud, ~$0.001/command)

```bash
export LLM_BACKEND=openai
export LLM_API_KEY=sk-...
python -m lever_runner "restart the web server"
# → LLM extracts "restart nginx" → matches systemctl restart nginx → runs it
```

### DeepInfra (cloud, ~$0.0002/command)

```bash
export LLM_BACKEND=deepinfra
export LLM_API_KEY=...
python -m lever_runner "check nginx status"
```

### Minimax (cloud)

```bash
export LLM_BACKEND=minimax
export LLM_API_KEY=...
```

### Fallback chain

```bash
export LLM_BACKEND=ollama
export LLM_FALLBACKS=openai,deepinfra,passthrough
```

If Ollama is down, it tries OpenAI. If that fails, DeepInfra. If everything fails, passthrough (your raw request becomes the intent). The chain always ends at passthrough — you're never stuck.

## Parameterized Commands

Commands can have `{{param}}` slots that get filled at execution time:

```bash
# Teach a template
python -m lever_runner teach "show logs for {{container}}" --command "docker logs --tail 100 {{container}}"

# Use it
python -m lever_runner "show logs for nginx"
# → runs: docker logs --tail 100 nginx

python -m lever_runner "show logs for postgres"
# → runs: docker logs --tail 100 postgres
```

Arguments are validated — shell metacharacters (`;`, `|`, `&`, `$`, backticks) are blocked. You can't inject `nginx; rm -rf /` because `;` gets rejected.

### Multi-parameter templates

```bash
python -m lever_runner teach "grep {{pattern}} in {{file}}" --command "grep -n {{pattern}} {{file}}"
python -m lever_runner "find TODO in main.py"
# → runs: grep -n TODO main.py
```

## Skill Packs

Skill packs are pre-built command sets for specific workflows.

### Using skill packs

```bash
# Import a skill pack
python -m lever_runner.import devops-skillpack.jsonl

# All commands are now available
python -m lever_runner "check kubernetes pods"
python -m lever_runner "show terraform plan"
```

### Creating skill packs

```bash
# Teach your commands, then export
python -m lever_runner teach "show k8s pods" --command "kubectl get pods"
python -m lever_runner teach "k8s pod logs" --command "kubectl logs {{pod}}"
python -m lever_runner.export > my-devops-pack.jsonl
```

### Built-in packs

- **System (77 commands):** Included by default. System admin, Docker, git, networking.
- **DevOps (45 commands):** Kubernetes, Terraform, systemd, nginx, Redis, PostgreSQL.
- **Git (32 commands):** Branching, rebasing, stash workflows, conflict resolution.

## Export to pincherOS

Export your taught commands as `.nail` files for pincherOS — portable reflex caching that works on edge devices (Raspberry Pi, ARM servers):

```bash
python -m lever_runner export-nail --output my-reflexes.nail

# On the target device
pincher import my-reflexes.nail
```

The `.nail` file includes embedding vectors for instant similarity search on import. No re-embedding needed.

## Running as a Service

### Telegram Bot

```bash
export TELEGRAM_BOT_TOKEN=...
export LLM_BACKEND=ollama
lever-runner-bot
```

Commands in Telegram:
- `/do check disk usage` — execute a command
- `/teach show docker containers | docker ps` — teach a new command
- `/status` — show system status
- `/commands` — list known commands
- `/stats show disk usage` — detailed command stats

### HTTP API

```bash
lever-runner-http
# Starts on http://localhost:8765

# Execute a command
curl -X POST http://localhost:8765/run \
  -d '{"request": "check disk usage"}' \
  -H 'content-type: application/json'

# Health check
curl http://localhost:8765/healthz
```

### Docker Compose

```bash
docker-compose up -d
```

## Diagnostics

```bash
lever-runner-doctor
```

Checks: Python version, dependencies, database, embedding model, LLM connectivity, disk space, and permissions.

## What's Next?

- **[CONTRIBUTING.md](../CONTRIBUTING.md)** — Add skill packs, LLM backends, or core features
- **[BENCHMARKS.md](../BENCHMARKS.md)** — Detailed token and cost comparisons
- **[pincherOS](https://github.com/SuperInstance/pincherOS)** — Rust agent runtime for edge deployment
- **[superinstance-ecosystem](https://github.com/SuperInstance/superinstance-ecosystem)** — Four-layer agent architecture
