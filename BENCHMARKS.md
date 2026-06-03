# Benchmarks — Lever-Runner Token & Cost Analysis

> **Reproduce yourself:** `python -m lever_runner.benchmark`

## Methodology

The benchmark runs a fixed 20-task suite in `passthrough` mode (no LLM API
calls). It measures the **embedding token cost** plus the **intent-system-prompt**
token cost — the overhead that exists on every command regardless of backend.
The hosted-LLM cost is then added analytically based on the actual system prompt
size.

### Token counting

- Passthrough mode: ~6 tok/cmd (embedding only; the user request is used
  verbatim as the intent phrase, so there's zero LLM I/O).
- Hosted LLM mode: system prompt (~58 tok) + user message (~10 tok) +
  LLM output (~8 tok) ≈ **76 tok/cmd**.
- The system prompt is a single fixed string — no tool schemas, no examples
  beyond 3 short lines, no chain-of-thought.

## Headline results

| Mode | Tokens / command | Reproduce |
|---|---|---|
| **Passthrough** (`LLM_BACKEND=passthrough`) | **~6** | `python -m lever_runner.benchmark` |
| **Hosted LLM** (DeepInfra Llama-3.1-8B) | **~76** | set `LLM_BACKEND=deepinfra` and re-run |
| **OpenAI function-calling** (typical) | **2,000 – 5,000** | see notes below |

### Why the gap?

OpenAI function-calling agents ship the **entire tool schema** in every prompt.
A typical agent with 20-50 tools spends 1,500-5,000 tokens on schema alone,
*before* the user's message. Lever-Runner sends a 58-token system prompt and
gets back an 8-token phrase. The command lookup is a local cosine search —
zero tokens.

## Cost per 1,000 commands

| Mode | Tokens / cmd | Cost / 1K cmds | Model used for estimate |
|---|---|---|---|
| Passthrough | ~6 | **$0.00** | no LLM |
| DeepInfra (Llama-3.1-8B) | ~76 | **$0.0018** | $0.02/M in, $0.03/M out |
| OpenAI gpt-4o-mini (func call) | ~3,000 | **$0.60** | $0.15/M in, $0.60/M out |
| OpenAI gpt-4o (func call) | ~3,000 | **$22.50** | $2.50/M in, $10.00/M out |

### Monthly cost projection

| Commands / day | Passthrough | DeepInfra | gpt-4o-mini func call | gpt-4o func call |
|---|---|---|---|---|
| 10 | $0.00 | $0.00 | $0.18 | $6.75 |
| 100 | $0.00 | $0.01 | $1.80 | $67.50 |
| 1,000 | $0.00 | $0.05 | $18.00 | $675.00 |

_(Monthly = 30 days × daily commands × cost / 1K cmds × count-in-thousands)_

## The system prompt

For reference, the entire LLM prompt that produces an intent phrase:

```
You compress a user request into a short verb-noun phrase of 3-8 words.
Output ONLY the phrase, lowercase, no punctuation, no quotes, no prefix.
Examples:
  'can you check how much disk I have left?' -> show disk usage
  'restart nginx' -> restart nginx
  'what's eating my CPU?' -> show top cpu processes
```

That's it. 58 tokens. Every command you run costs those 58 tokens plus
whatever your request adds (~10 tokens) and the response (~8 tokens).

## Reproduce

```bash
# Passthrough mode (zero cost):
export LLM_BACKEND=passthrough
python -m lever_runner.benchmark

# Hosted LLM mode (requires API key):
export LLM_BACKEND=deepinfra
export DEEPINFRA_API_KEY=your-key
python -m lever_runner.benchmark
```

Expected output:

```
benchmark: 20 tasks, 67 commands in table
backend   : passthrough (no real LLM calls)
...
============================================================
tasks run           : 20
successes           : 20/20
avg intent tokens   : ~6
avg embed tokens    : ~6
avg total per cmd   : ~6
target              : < 200
============================================================
```

---

## Real Hardware Benchmarks

Detailed latency and throughput benchmarks measured on an **NVIDIA RTX 4050 Laptop GPU**:

- **Full results:** [`benchmarks/BENCHMARK-RESULTS.md`](benchmarks/BENCHMARK-RESULTS.md)
- **Raw data:** [`benchmarks/results-rtx4050.json`](benchmarks/results-rtx4050.json)
- **Benchmark script:** [`benchmarks/run_gpu_benchmarks.py`](benchmarks/run_gpu_benchmarks.py)

### Quick summary (RTX 4050)

| Operation | p50 latency |
|---|---|
| Vector search (embed + query) | 7.6 ms |
| Full orchestrator (end-to-end) | 7.6 ms |
| Teach (new command) | 8.1 ms |
| Template matching | 1.7 µs |
| GPU single-text embedding | 2.6 ms |
| CPU single-text embedding | 6.7 ms |

GPU acceleration gives **2.6× faster** single-text embedding vs CPU for this workload.

---

_These benchmarks were measured on commit `main`. Re-run `python -m
lever_runner.benchmark` on your own hardware for authoritative numbers._
