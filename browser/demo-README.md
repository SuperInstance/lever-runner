# lever-runner Browser Demo

**Zero server. Zero API keys. Just open the file.**

## Quick Start

```bash
# Option 1: Just open it
open browser/demo.html          # macOS
xdg-open browser/demo.html      # Linux
start browser/demo.html         # Windows

# Option 2: Simple HTTP server (for dev)
python3 -m http.server 8080
# → http://localhost:8080/browser/demo.html
```

That's it. No install, no dependencies, no API keys.

## What You'll See

### The Terminal
Type natural language commands in English. The demo finds and displays matching shell commands.

### The Three-Gate Pipeline
Every query flows through three gates, visualized in real-time:

1. **Gate 1 — Intent Hash** (Rust, ~50µs)
   - Hashes your query with BLAKE2b
   - O(1) exact match lookup
   - If hit: done. Skip gates 2-3.

2. **Gate 2 — Vector Search** (Python, ~5-10ms)
   - Embeds your query with position-aware hashing
   - Cosine similarity search against command database
   - If confidence > 65%: done. Skip gate 3.

3. **Gate 3 — LLM Fallback** (~500ms)
   - Only fires when Gates 1-2 both miss
   - Simulated LLM call (in production, this hits your local Ollama)
   - Consumes full token budget

### Token Counter
Shows tokens saved per query. lever-runner typically uses 15 tokens vs 800+ for raw LLM prompting.

## Features

### 20+ Pre-loaded Commands
System, Docker, Git, files, network, Python — common DevOps commands ready to go.

### Teach Mode
Add your own commands in the right panel:
- Enter the natural language intent
- Enter the shell command
- Click "Teach" — it's instantly available

### Export
Click "Export JSON" to download all commands (built-in + taught) as a JSON file. Import into your real lever-runner instance.

### Persistence
Taught commands are saved to localStorage — they survive page reloads.

## Architecture

```
Pure vanilla HTML/CSS/JS — no frameworks, no dependencies
Position-aware embedding: 64-dim hash-based vectors
BLAKE2b intent hashing via Web Crypto API
Dark terminal aesthetic with animated pipeline
```

This demo simulates lever-runner's core loop. For the real CLI with LanceDB, Ollama integration, and sandboxed execution, see the [main README](../README.md).
