#!/usr/bin/env python3
"""benchmark.py — compare GPU vs CPU vector search performance.

Usage:
    python gpu/benchmark.py [--sizes 100 1000 10000 100000] [--dim 384] [--top-k 3]

Runs cosine similarity search at each database size, 10 iterations,
reports CPU and GPU latency and speedup.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add parent dir to path so we can import lever_runner
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lever_runner.cuda_backend import benchmark, get_status, report


def main():
    parser = argparse.ArgumentParser(description="GPU vs CPU vector search benchmark")
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1_000, 10_000, 100_000],
                        help="Database sizes to benchmark")
    parser.add_argument("--dim", type=int, default=384, help="Vector dimension")
    parser.add_argument("--top-k", type=int, default=3, help="Number of results")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    print("=" * 60)
    print("lever-runner GPU Benchmark")
    print("=" * 60)
    print()
    print(report())
    print()

    results = benchmark(sizes=args.sizes, dim=args.dim, top_k=args.top_k)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    # Table output
    print(f"{'N':>10} | {'CPU (ms)':>10} | {'GPU (ms)':>10} | {'Speedup':>8} | Backend")
    print("-" * 60)
    for n, r in sorted(results.items()):
        print(f"{n:>10,} | {r['cpu_ms']:>10.3f} | {r['gpu_ms']:>10.3f} | {r['speedup']:>7.1f}x | {r['backend']}")

    print()


if __name__ == "__main__":
    main()
