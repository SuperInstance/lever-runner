# Benchmark Results — NVIDIA RTX 4050 Laptop GPU

> **Hardware:** NVIDIA GeForce RTX 4050 Laptop GPU (6GB VRAM, CUDA 12.1)  
> **Date:** 2026-06-03  
> **Python:** 3.10.12 | **PyTorch:** 2.4.1+cu121  
> **Model:** sentence-transformers/all-MiniLM-L6-v2 (384-dim)

## Latency Summary

| Operation | p50 | p99 | Avg |
|---|---|---|---|
| **Vector search** (embed + LanceDB query) | 7.6 ms | 30.3 ms | — |
| **Full orchestrator** (intent → match) | 7.6 ms | 10.1 ms | — |
| **Teach** (new command insert) | 8.1 ms | — | — |
| **Template matching** (parse + substitute) | 1.7 µs | — | 1.9 µs |
| **Passthrough match** (embed + find_best) | 7.8 ms | —* | 101.8 ms |

*\* The passthrough p99 of 9,309ms is a cold-start outlier (first query loads model). Subsequent queries stabilize at ~7-10ms.*

## Embedding Performance: CPU vs GPU

| Metric | CPU | GPU | Speedup |
|---|---|---|---|
| Single-text encode | 6.70 ms | 2.63 ms | **2.6×** |
| Batch encode (100 texts) | 215.6 ms (2.2ms/text) | 321.0 ms (3.2ms/text) | 0.7× (overhead) |

### Key Findings

- **GPU wins for single-text latency** — 2.6ms vs 6.7ms (2.6× faster)
- **CPU wins for batch** — small model (22MB) doesn't saturate GPU; transfer overhead dominates
- **Recommendation:** For lever-runner's use case (single-text embed per command), GPU acceleration provides meaningful latency improvement

## Throughput

| Operation | Throughput |
|---|---|
| **Teach** (new command) | 122.3 commands/sec |
| **Vector search** (query) | ~131 queries/sec (at p50) |
| **Full orchestrator** | ~132 commands/sec (at p50) |

## Architecture Notes

- LanceDB stores embeddings on-disk with cosine similarity search
- Template commands use `{{placeholder}}` syntax with regex-based parsing (sub-microsecond)
- The passthrough backend skips LLM calls entirely — all latency is embedding + vector search
- First query pays model loading cost (~500ms); subsequent queries hit cached model

## Reproduce

```bash
cd lever-runner
PYTHONPATH=src python3 benchmarks/run_gpu_benchmarks.py
```

Raw data: [`results-rtx4050.json`](./results-rtx4050.json)
