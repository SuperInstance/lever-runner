"""Real hardware benchmarks for lever-runner on RTX 4050"""
import time
import json
import subprocess
import sys
import os

os.environ["LLM_BACKEND"] = "passthrough"

# Ensure DB is initialized
subprocess.run([sys.executable, "init_db.py", "--yes"], capture_output=True)

results = {}

# Import once, reuse the same store instance to avoid loading model multiple times
from lever_runner.store import CommandStore
store = CommandStore()
print("[1/5] Store loaded. Running passthrough match benchmark...")

# Benchmark 1: Raw intent matching latency (passthrough)
times = []
for i in range(100):
    start = time.perf_counter()
    store.find_best("check disk usage")
    times.append((time.perf_counter() - start) * 1000)
results["passthrough_match_p50_ms"] = round(sorted(times)[50], 3)
results["passthrough_match_p99_ms"] = round(sorted(times)[99], 3)
results["passthrough_match_avg_ms"] = round(sum(times) / len(times), 3)
print(f"  p50={results['passthrough_match_p50_ms']}ms, p99={results['passthrough_match_p99_ms']}ms")

# Benchmark 2: Full orchestrator latency (passing reusable store)
print("[2/5] Running orchestrator benchmark...")
from lever_runner.orchestrator import do as orch_do
times2 = []
for i in range(50):
    start = time.perf_counter()
    try:
        result = orch_do("check disk usage", auto_run=False, store=store)
    except Exception as e:
        pass
    times2.append((time.perf_counter() - start) * 1000)
results["full_orchestrator_p50_ms"] = round(sorted(times2)[25], 3)
results["full_orchestrator_p99_ms"] = round(sorted(times2)[49], 3)
print(f"  p50={results['full_orchestrator_p50_ms']}ms, p99={results['full_orchestrator_p99_ms']}ms")

# Benchmark 3: LanceDB vector search
print("[3/5] Running vector search benchmark...")
times3 = []
for i in range(50):
    start = time.perf_counter()
    store.find_best("show running processes")
    times3.append((time.perf_counter() - start) * 1000)
results["vector_search_p50_ms"] = round(sorted(times3)[25], 3)
results["vector_search_p99_ms"] = round(sorted(times3)[49], 3)
print(f"  p50={results['vector_search_p50_ms']}ms, p99={results['vector_search_p99_ms']}ms")

# Benchmark 4: Template matching (parameterized commands)
print("[4/5] Running template matching benchmark...")
try:
    from lever_runner.store import has_placeholders, get_placeholders, substitute_args
    times4 = []
    for i in range(100):
        start = time.perf_counter()
        has_placeholders("show logs for {{container}}")
        get_placeholders("show logs for {{container}}")
        substitute_args("docker logs {{container}}", {"container": "nginx"})
        times4.append((time.perf_counter() - start) * 1000)
    results["template_match_p50_us"] = round(sorted(times4)[50] * 1000, 1)  # microseconds
    results["template_match_avg_us"] = round((sum(times4) / len(times4)) * 1000, 1)
    print(f"  p50={results['template_match_p50_us']}us, avg={results['template_match_avg_us']}us")
except Exception as e:
    results["template_error"] = str(e)
    print(f"  Error: {e}")

# Benchmark 5: Teach throughput
print("[5/5] Running teach throughput benchmark...")
times5 = []
for i in range(20):
    start = time.perf_counter()
    store.teach(f"benchmark test {i}", f"echo 'test {i}'")
    times5.append((time.perf_counter() - start) * 1000)
results["teach_p50_ms"] = round(sorted(times5)[10], 3)
results["teach_throughput_per_sec"] = round(1000 / (sum(times5) / len(times5)), 1)
print(f"  p50={results['teach_p50_ms']}ms, throughput={results['teach_throughput_per_sec']}/sec")

# System info
import platform
import torch
results["system"] = {
    "cpu": platform.processor(),
    "ram_gb": "32",
    "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "none",
    "gpu_vram_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1) if torch.cuda.is_available() else 0,
    "python": platform.python_version(),
    "pytorch": torch.__version__,
    "cuda_version": torch.version.cuda if torch.cuda.is_available() else "n/a",
}

# Output
print("\n" + json.dumps(results, indent=2))
with open("benchmarks/results-rtx4050.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to benchmarks/results-rtx4050.json")
