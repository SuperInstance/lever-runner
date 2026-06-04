# Browser Strategy for Lever-Runner

> Analysis of options for running lever-runner in a browser — two tiers evaluated.

## What Lever-Runner Actually Needs

Before evaluating options, here's what the stack requires:

| Component | What it does | Dependencies |
|-----------|-------------|--------------|
| **Intent extractor** | Compresses user request → 3-8 word phrase via LLM | `requests`, HTTP to LLM API |
| **Embedding** | Turns phrase → 384-dim vector (MiniLM) or 64-dim hash | `sentence-transformers`, `torch` (for MiniLM); `hashlib` + `numpy` (for hash) |
| **Vector store** | Stores `{phrase, command, trust, embedding}`, does cosine search | `lancedb`, `pyarrow`, `pandas` |
| **Executor** | Runs shell commands in a sandbox with timeout | `subprocess`, `resource`, `signal` — **OS-level, impossible in browser** |
| **FastLoop** | Sub-ms input validation (rate limit, failure cache, metachar detection) | Pure Python, no OS deps |
| **Trust scoring** | Bumps success/failure counters per command | Part of store, no extra deps |
| **Telegram bot** | `/do`, `/teach`, `/status` handlers | `python-telegram-bot` — not needed in browser |

**Key insight:** The core value loop is: *user types request → embed → vector search → show matched command*. The executor (actually running shell commands) is the part that *can't* work in a browser. A browser version is fundamentally a **command lookup & teaching tool**, not a command runner.

---

## Tier 1: Pure Browser (Zero Server, CDN/Cache)

The user opens a URL and everything runs locally in their browser. No server, no API keys, no install.

### Option 1.1: Pyodide (Python in WebAssembly)

**How it works:** Pyodide compiles CPython 3.12+ to WebAssembly. You load it from CDN, it runs your Python code in the browser.

**Feasibility:**
- ✅ `numpy` — works natively in Pyodide
- ✅ `hashlib`, `re`, `json`, `os` (subset) — stdlib works
- ✅ The hash-based embedding methods (`position_aware_embed`, `hash_embed`) — pure Python + numpy, will work
- ❌ `sentence-transformers` + `torch` — PyTorch has experimental Pyodide support but it's huge (~200MB WASM) and MiniLM model loading is untested/flaky. **This is the blocker.**
- ❌ `lancedb` — depends on native Rust extensions (Lance format). Does not compile to WASM. **Hard blocker.**
- ⚠️ `subprocess`, `resource`, `signal` — not available in browser (expected, we'd skip execution)

**Verdict:** LanceDB is a hard blocker. You'd need to replace it with a pure-Python vector store (e.g., a simple numpy-based cosine similarity over an in-memory list). Sentence-transformers is a soft blocker — you can use hash-based embeddings instead. With those swaps, ~60% of the codebase works.

**User experience:** ~10-15 seconds initial load (Pyodide + packages), then fast. Works offline after first load (Service Worker caching).

**Cost:** $0 for everyone. CDN hosting is free (GitHub Pages, Netlify).

**Limitations:** No real vector DB (replaced with numpy brute-force — fine for <10K commands). No LLM (use passthrough mode). No command execution (browser sandbox).

**Effort:** 3-5 days. Replace LanceDB with numpy-based store, strip executor/bot imports, build minimal HTML UI.

### Option 1.2: PyScript

**How it works:** PyScript = Pyodide + nice HTML tags (`<py-script>`, `<py-repl>`) + Pyodide's package manager.

**Feasibility:** Same as Pyodide — it *is* Pyodide under the hood. Same blockers (lancedb, torch).

**User experience:** Slightly nicer developer experience (HTML-first), but end-user experience is identical to Pyodide.

**Cost:** $0.

**Limitations:** Same as Pyodide. PyScript adds some abstraction overhead.

**Effort:** 3-5 days (same as Pyodide, just different packaging).

### Option 1.3: WebAssembly Compile (Custom)

**How it works:** Compile lever-runner's core logic to WASM using something like `pyodide` (above) or rewrite in Rust/C and compile to WASM.

**Feasibility:**
- Python → WASM is Pyodide (see above).
- Rust rewrite: possible but massive effort for a Tier 1 demo.
- C/C++ rewrite: same.

**Verdict:** Not a separate option — it's what Pyodide already does, or a full rewrite.

**Effort:** Weeks for a Rust/C rewrite. Not worth it for Tier 1.

### Option 1.4: JavaScript Port (Recommended for Tier 1)

**How it works:** Rewrite just the core logic (embedding + command matching + teaching) in ~500 lines of JavaScript. Ship as a static site.

**Feasibility:**
- ✅ Hash-based embedding: trivial in JS (Web Crypto API for blake2b, or use a JS hash lib)
- ✅ Vector search: brute-force cosine similarity over a JS array, sub-ms for <10K commands
- ✅ Intent extraction: passthrough mode (no LLM) — just normalize the input
- ✅ Teaching: push new {phrase, command, embedding} to the in-memory array, persist to IndexedDB
- ✅ Import/export: serialize to JSONL, download/upload files
- ❌ No LLM intent compression (passthrough only)
- ❌ No command execution (browser sandbox)

**User experience:** Instant load (< 100KB JS bundle). Works offline. No install. Teach and lookup commands in a clean UI.

**Cost:** $0. Host on GitHub Pages.

**Limitations:** Passthrough mode only (no LLM). No execution. Hash-based embeddings have ~44% top-1 accuracy vs ~95% with MiniLM (per the codebase's own benchmarks). IndexedDB caps at ~50MB but that's millions of commands.

**Effort:** 2-4 days for a skilled JS developer. The core is simple:
```javascript
// Embedding: position-aware hash (from store.py, ported to JS)
function positionAwareEmbed(text, dim = 64) {
  const words = text.toLowerCase().split(/\s+/);
  const vec = new Float32Array(dim);
  for (let i = 0; i < words.length; i++) {
    const hash = blake2b(`${i}:${words[i]}`, dim);
    const weight = 1.0 / (1 + i * 0.5);
    for (let j = 0; j < dim; j++) vec[j] += hash[j] * weight;
  }
  // normalize
  const norm = Math.sqrt(vec.reduce((s, v) => s + v * v, 0));
  if (norm > 0) for (let j = 0; j < dim; j++) vec[j] /= norm;
  return vec;
}

// Search: cosine similarity
function findBest(phrase, commands, topK = 3) {
  const query = positionAwareEmbed(phrase);
  return commands
    .map(c => ({ ...c, similarity: cosineSim(query, c.embedding) }))
    .sort((a, b) => b.similarity - a.similarity)
    .slice(0, topK);
}
```

**Verdict:** Best Tier 1 option. Small, fast, works everywhere, zero deps.

### Option 1.5: Chrome Built-in AI (Gemini Nano)

**How it works:** Chrome 127+ ships with Gemini Nano, a small LLM that runs locally via `window.ai` API.

**Feasibility:**
- ✅ Could replace the LLM intent extraction — instead of passthrough, use Gemini Nano to compress "check disk usage on the server" → "show disk usage"
- ⚠️ `window.ai` is still experimental (behind flags in many builds)
- ⚠️ Only available in Chrome (not Firefox, Safari)
- ❌ Doesn't solve the vector store or embedding problems — still need a JS port of those

**Verdict:** Not a standalone option. Could be *added* to the JS port (Option 1.4) as an enhancement — when Chrome's built-in AI is available, use it for intent compression instead of passthrough.

**Effort:** +1 day on top of Option 1.4.

---

### Tier 1 Recommendation: **JavaScript Port (Option 1.4)**

With optional Chrome Built-in AI enhancement (Option 1.5).

---

## Tier 2: Container-Based (Browser UI + Remote Container)

Full-featured version that runs in a container, accessible via browser. This gets you *everything* — LLM intent extraction, sentence-transformers embeddings, LanceDB, even command execution (inside the container).

### Option 2.1: GitHub Codespaces

**How it works:** User forks the repo, clicks "Open in Codespaces", gets a VS Code editor + terminal in the browser with the full Python environment.

**Feasibility:**
- ✅ Full Python 3.12, all dependencies installable
- ✅ LanceDB, sentence-transformers, Ollama (can run in the container)
- ✅ Command execution works (it's a real Linux container)
- ✅ Telegram bot can run alongside

**User experience:** 3-5 clicks. 2-4 minutes for container startup + package install on first launch. Subsequent starts ~30 seconds. Users need a GitHub account.

**Cost:**
- Free tier: 120 core-hours/month, 15GB storage (enough for evaluation)
- Paid: $0.18/hour for 2-core, 4GB RAM
- Cost to us: $0 (user pays or uses free tier)

**Limitations:** Container sleeps after 30 min inactivity. Not suitable for always-on bot. Users need GitHub accounts.

**Effort:** 1-2 days. Create `.devcontainer/devcontainer.json` + `postCreateCommand.sh` that installs deps and seeds the DB. Maybe add a simple web UI.

### Option 2.2: Gitpod

**How it works:** Same as Codespaces but Gitpod's own infrastructure. More configurable (custom Docker images, prebuilt workspaces).

**Feasibility:** Same as Codespaces — full Linux container.

**User experience:** Similar to Codespaces. One-click from repo (Gitpod button in README). 1-3 min first start.

**Cost:**
- Free tier: 50 hours/month
- Paid: starts at $9/month for individuals

**Limitations:** Same as Codespaces. Free tier is more limited.

**Effort:** 1 day. Add `.gitpod.yml` with init tasks.

### Option 2.3: Cloudflare Containers (Coming Soon)

**How it works:** Cloudflare is building container hosting (currently in beta/limited). Would spin up on demand, shut down to save costs.

**Feasibility:** Unknown — the product isn't fully GA yet. Not a viable option today.

**Effort:** N/A — wait for GA.

### Option 2.4: Google Cloud Run

**How it works:** Serverless containers. HTTP request → container starts → serves request → shuts down. Cold start ~2-5 seconds.

**Feasibility:**
- ✅ Full container, all deps work
- ⚠️ Cold start is painful with heavy Python deps (torch ~2GB, sentence-transformers). First request after idle could take 10-30 seconds.
- ⚠️ No persistent disk — LanceDB data lost on restart. Need to use external storage (Cloud Storage, Firestore) or accept ephemeral data.
- ⚠️ Memory: MiniLM + torch needs ~1GB minimum. Cloud Run max is 32GB but pricing scales.

**User experience:** Web UI would work. Cold starts are the pain point. No persistent state without extra setup.

**Cost:**
- Free tier: 2 million requests/month, 360,000 GB-seconds
- For a demo: likely under $5/month
- For production with persistent data: $10-50/month depending on storage

**Limitations:** Cold starts with heavy ML deps. No persistent local storage. Requires GCP account.

**Effort:** 3-5 days. Dockerfile + Cloud Run config + replace LanceDB with cloud storage adapter.

### Option 2.5: Fly.io

**How it works:** Edge-deployed containers. Persistent volumes available. Auto-stop/start to save costs.

**Feasibility:**
- ✅ Full container, all deps
- ✅ Persistent volumes — LanceDB data survives restarts
- ✅ Auto-stop machines when idle (saves money)
- ✅ Can run Ollama in the container (need enough RAM)
- ⚠️ Cold start after auto-stop: ~5-10 seconds with heavy deps
- ⚠️ Need at least 1GB RAM (2GB recommended for sentence-transformers)

**User experience:** Fast when warm. Cold start is noticeable. Persistent state works well.

**Cost:**
- Free tier: 3 shared-cpu-1x VMs with 256MB RAM (not enough for torch)
- Paid: ~$1.94/month for 1GB persistent volume + ~$5.67/month for 1GB RAM VM running 24/7
- With auto-stop: ~$1-3/month for light usage
- 2GB RAM VM: ~$11/month

**Limitations:** Need to manage machine lifecycle. Free tier RAM too small for ML deps.

**Effort:** 2-3 days. Dockerfile + `fly.toml` + persistent volume config.

### Option 2.6: JupyterLite

**How it works:** Jupyter notebooks running entirely in the browser via Pyodide. No server.

**Feasibility:**
- Same as Pyodide (Option 1.1) — it *is* Pyodide
- ❌ LanceDB hard blocker
- ❌ sentence-transformers soft blocker
- Provides a notebook interface instead of a custom UI

**Verdict:** Not recommended. Same limitations as Pyodide but with a notebook UI that's overkill for what lever-runner needs. Better to build a purpose-built UI with the JS port.

---

### Tier 2 Recommendation: **GitHub Codespaces (Option 2.1)**

For lowest-friction "try it now" experience. **Fly.io (Option 2.5)** as the production hosting target.

---

## Implementation Plans

### Tier 1 MVP: JavaScript Port

**What to build:** A single-page app at `lever-runner.pages.dev` (or similar) that lets users:
1. Type a natural language request
2. See the best-matching command (with confidence score)
3. Teach new commands (phrase + shell command)
4. Import/export their command database as JSONL
5. All data stored in IndexedDB, persists across sessions

**Stack:**
- Vanilla JS (or Preact for minimal UI framework)
- Tailwind CSS (via CDN)
- IndexedDB for persistence
- No build step — just `index.html`

**Architecture:**

```
lever-runner-web/
├── index.html          # Single page, loads everything
├── app.js              # Main app logic, UI
├── embed.js            # Hash-based embedding (ported from store.py)
├── store.js            # Command store (IndexedDB + vector search)
├── seed-commands.js    # Pre-loaded seed pack (exported from Python)
├── style.css           # Minimal styles
└── sw.js               # Service Worker for offline
```

**Key porting notes:**

1. **Embedding:** Port `position_aware_embed()` from `store.py`. Use `crypto.subtle` for blake2b or use a 1KB blake2b JS library. The hash-based embedding is ~44% top-1 accuracy — acceptable for a demo.

2. **Store:** Replace LanceDB with an IndexedDB-backed array + brute-force cosine search. For <10K commands, this is <5ms.

3. **Intent extraction:** Passthrough mode only. Normalize input the same way `_normalize()` does in `intent_extractor.py`.

4. **Trust scoring:** Port the `update_trust()` logic. Simple arithmetic.

5. **Seed pack:** Export the 66 commands from `init_db.py` as a JS array with pre-computed embeddings.

6. **Optional: Chrome Built-in AI** — detect `window.ai` API, use it for intent compression when available:
```javascript
async function extractIntent(userRequest) {
  if ('ai' in window && (await window.ai.capabilities())) {
    const session = await window.ai.createTextSession();
    return session.prompt(COMPRESS_PROMPT + userRequest);
  }
  // Fallback: passthrough
  return normalize(userRequest);
}
```

**Timeline:** 3-4 days.

### Tier 2 MVP: GitHub Codespaces

**What to build:** A `.devcontainer/` config that gives users a one-click "Open in browser" experience with the full lever-runner stack, plus a simple web UI.

**Files to create:**

```yaml
# .devcontainer/devcontainer.json
{
  "name": "lever-runner",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "features": {
    "ghcr.io/devcontainers/features/docker-in-docker:2": {}
  },
  "postCreateCommand": "pip install -e . && python -c 'from lever_runner.store import CommandStore; CommandStore()'",
  "forwardPorts": [8765],
  "portsAttributes": {
    "8765": { "label": "Lever-Runner API", "onAutoForward": "openPreview" }
  },
  "customizations": {
    "vscode": {
      "extensions": ["ms-python.python"]
    }
  }
}
```

**Optional: Add a web UI** (a simple `index.html` that talks to the HTTP API on port 8765):
- Input field for natural language request
- Button to execute (via `/run` endpoint)
- Button to teach new commands
- Display matched command + trust score
- List all commands

**Timeline:** 1-2 days for devcontainer setup + basic web UI.

### Tier 2 Production: Fly.io

**For a persistent, always-on deployment:**

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -e .

# Pre-download embedding model during build
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

EXPOSE 8765
VOLUME /data

ENV LANCEDB_PATH=/data/lever.lancedb
ENV LLM_BACKEND=passthrough

CMD ["python", "-m", "lever_runner.http_api"]
```

```toml
# fly.toml
app = "lever-runner"
primary_region = "sjc"

[build]
  dockerfile = "Dockerfile"

[http_service]
  internal_port = 8765
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[mounts]
  source = "lever_data"
  destination = "/data"

[[vm]]
  memory = "2gb"
  cpu_kind = "shared"
  cpus = 1
```

**Cost estimate:** ~$5-11/month with auto-stop (only runs when receiving requests).

**CI/CD:** GitHub Actions workflow that builds and deploys on push to `main`:
```yaml
# .github/workflows/deploy-fly.yml
name: Deploy to Fly.io
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

---

## Summary Matrix

| Option | Feasibility | UX (clicks) | Cost (us) | Cost (user) | Limitations | Effort |
|--------|-------------|-------------|-----------|-------------|-------------|--------|
| **JS Port** ⭐ | ✅ Core works | 1 (open URL) | $0 | $0 | No LLM, no exec, hash embed only | 3-4 days |
| Pyodide/PyScript | ⚠️ Needs LanceDB swap | 1 | $0 | $0 | Same as JS + slow load (15s) | 3-5 days |
| WASM compile | ❌ Not viable standalone | — | — | — | Same as Pyodide + more work | Weeks |
| Chrome AI | ⚠️ Enhancement only | — | — | — | Chrome only, experimental | +1 day |
| **Codespaces** ⭐ | ✅ Full stack | 3-5 | $0 | $0 (free tier) | Container sleeps, needs GH account | 1-2 days |
| Gitpod | ✅ Full stack | 3-5 | $0 | $0 (50hr/mo) | Smaller free tier | 1 day |
| Cloudflare | ❌ Not GA yet | — | — | — | Product doesn't exist yet | N/A |
| Cloud Run | ⚠️ Cold starts | 1 | $5-50/mo | $0 | Cold start, no persistent disk | 3-5 days |
| **Fly.io** ⭐ | ✅ Full stack | 1 | $5-11/mo | $0 | Auto-stop cold start | 2-3 days |
| JupyterLite | ⚠️ Same as Pyodide | 1 | $0 | $0 | Notebook UI overkill, same blockers | 3-5 days |

**⭐ = Recommended for that tier.**

## Action Plan

1. **Week 1:** Build the JS port (Tier 1). Ship to GitHub Pages. This is the "zero-friction demo" that anyone can try.
2. **Week 1 (parallel):** Add `.devcontainer/` for Codespaces (Tier 2 quick-start). Update README with "Try in browser" button.
3. **Week 2:** If there's demand for a persistent hosted version, set up Fly.io deployment (Tier 2 production).
4. **Future:** When Chrome's Built-in AI goes stable, add it as an enhancement to the JS port for better intent compression without a server.
