"""
cuda_backend.py — GPU-accelerated vector search and embedding for lever-runner.

Detects CUDA availability and accelerates Gate 2 (vector search) when possible.
Falls back transparently to the existing CPU path when GPU is unavailable.

Integration with the three-gate architecture:
    Gate 1: CPU (hash validation — already fast, no GPU benefit)
    Gate 2: GPU (vector search — the bottleneck this accelerates)
    Gate 3: LLM (intent extraction — unchanged)

Detection order:
    1. PyTorch (torch.cuda)
    2. CuPy (cupy)
    3. PyCUDA (pycuda.driver)
    4. ctypes (pre-compiled .so from gpu/)
    5. CPU fallback

Environment variables:
    LEVER_GPU_DISABLE=1     — force CPU path even if GPU is available
    LEVER_GPU_LIB=path      — override path to pre-compiled .so
    LEVER_GPU_DEVICE=int    — select specific GPU device (default: 0)
"""

from __future__ import annotations

import ctypes
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .cuda_kernels import COSINE_SEARCH_KERNEL, BATCH_EMBED_KERNEL, get_shared_lib_path

log = logging.getLogger("lever-runner.cuda")

# ---------------------------------------------------------------------------
# Backend enum
# ---------------------------------------------------------------------------

GPU_BACKENDS = ("torch", "cupy", "pycuda", "ctypes", "cpu")


@dataclass
class BackendStatus:
    name: str               # "torch" | "cupy" | "pycuda" | "ctypes" | "cpu"
    device_name: str        # e.g. "NVIDIA RTX 4090" or "CPU fallback"
    device_count: int       # number of GPUs, 0 if CPU
    memory_total_mb: float  # total GPU memory in MB, 0 if CPU
    memory_free_mb: float   # free GPU memory in MB, 0 if CPU


@dataclass
class SearchResult:
    indices: np.ndarray     # [top_k] int array of matched indices
    scores: np.ndarray      # [top_k] float array of similarity scores
    latency_ms: float       # search latency in milliseconds


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _detect_backend() -> str:
    """Return the best available GPU backend, or 'cpu'."""
    if os.getenv("LEVER_GPU_DISABLE", "").strip() in ("1", "true", "yes"):
        log.info("GPU disabled via LEVER_GPU_DISABLE")
        return "cpu"

    # 1. PyTorch
    try:
        import torch
        if torch.cuda.is_available():
            return "torch"
    except ImportError:
        pass

    # 2. CuPy
    try:
        import cupy
        if cupy.cuda.runtime.getDeviceCount() > 0:
            return "cupy"
    except (ImportError, Exception):
        pass

    # 3. PyCUDA
    try:
        import pycuda.driver as drv
        drv.init()
        if drv.Device.count > 0:
            return "pycuda"
    except (ImportError, Exception):
        pass

    # 4. ctypes — pre-compiled .so
    so_path = get_shared_lib_path()
    if so_path.exists():
        try:
            ctypes.CDLL(str(so_path))
            return "ctypes"
        except OSError:
            pass

    log.info("No GPU backend found; using CPU fallback")
    return "cpu"


def get_status() -> BackendStatus:
    """Report which backend is active and GPU info."""
    backend = _detect_backend()

    if backend == "cpu":
        return BackendStatus(
            name="cpu",
            device_name="CPU fallback",
            device_count=0,
            memory_total_mb=0.0,
            memory_free_mb=0.0,
        )

    try:
        if backend == "torch":
            import torch
            idx = int(os.getenv("LEVER_GPU_DEVICE", "0"))
            props = torch.cuda.get_device_properties(idx)
            free, total = torch.cuda.mem_get_info(idx)
            return BackendStatus(
                name="torch",
                device_name=props.name,
                device_count=torch.cuda.device_count(),
                memory_total_mb=total / (1024 * 1024),
                memory_free_mb=free / (1024 * 1024),
            )

        if backend == "cupy":
            import cupy
            idx = int(os.getenv("LEVER_GPU_DEVICE", "0"))
            dev = cupy.cuda.Device(idx)
            free, total = dev.mem_info
            return BackendStatus(
                name="cupy",
                device_name=cupy.cuda.runtime.getDeviceProperties(idx)["name"].decode(),
                device_count=cupy.cuda.runtime.getDeviceCount(),
                memory_total_mb=total / (1024 * 1024),
                memory_free_mb=free / (1024 * 1024),
            )

        if backend == "pycuda":
            import pycuda.driver as drv
            idx = int(os.getenv("LEVER_GPU_DEVICE", "0"))
            dev = drv.Device(idx)
            ctx = dev.make_context()
            try:
                free, total = drv.mem_get_info()
                return BackendStatus(
                    name="pycuda",
                    device_name=dev.name(),
                    device_count=drv.Device.count,
                    memory_total_mb=total / (1024 * 1024),
                    memory_free_mb=free / (1024 * 1024),
                )
            finally:
                ctx.pop()

        if backend == "ctypes":
            return BackendStatus(
                name="ctypes",
                device_name="GPU (ctypes fallback)",
                device_count=1,
                memory_total_mb=0.0,
                memory_free_mb=0.0,
            )
    except Exception as e:
        log.warning("Failed to query GPU status for backend %r: %s", backend, e)

    return BackendStatus(name="cpu", device_name="CPU fallback", device_count=0,
                         memory_total_mb=0.0, memory_free_mb=0.0)


# ---------------------------------------------------------------------------
# GPU vector search (Gate 2 accelerator)
# ---------------------------------------------------------------------------

class GPUVectorSearch:
    """GPU-accelerated cosine similarity search.

    Moves the database vectors to GPU once, then searches are done entirely
    on the device. Falls back to numpy CPU if GPU is unavailable.
    """

    def __init__(self, dim: int = 384, top_k: int = 3) -> None:
        self.dim = dim
        self.top_k = top_k
        self.backend = _detect_backend()
        self._db_gpu = None       # GPU-side database matrix
        self._db_cpu = None       # CPU-side copy for fallback
        self._db_size = 0

        if self.backend != "cpu":
            log.info("GPU vector search using backend: %s (dim=%d)", self.backend, dim)

    @property
    def is_gpu(self) -> bool:
        return self.backend != "cpu"

    def load_database(self, vectors: np.ndarray) -> None:
        """Load database vectors onto the GPU. vectors: [N, dim] float32."""
        vectors = np.ascontiguousarray(vectors, dtype=np.float32)
        self._db_cpu = vectors
        self._db_size = vectors.shape[0]

        if self.backend == "cpu":
            return

        if self.backend == "torch":
            import torch
            self._db_gpu = torch.from_numpy(vectors).cuda()
            return

        if self.backend == "cupy":
            import cupy
            self._db_gpu = cupy.asarray(vectors)
            return

        # For pycuda/ctypes, keep on CPU — we'll upload per-query
        self._db_gpu = vectors

    def search(self, query: np.ndarray) -> SearchResult:
        """Search for top_k nearest neighbors to query vector.

        query: [dim] float32
        Returns SearchResult with indices, similarity scores, and latency.
        """
        query = np.ascontiguousarray(query, dtype=np.float32).ravel()
        t0 = time.perf_counter()

        if self.backend == "cpu" or self._db_cpu is not None and self._db_gpu is None:
            result = self._search_cpu(query)
        elif self.backend == "torch":
            result = self._search_torch(query)
        elif self.backend == "cupy":
            result = self._search_cupy(query)
        else:
            result = self._search_cpu(query)

        result.latency_ms = (time.perf_counter() - t0) * 1000
        return result

    def _search_cpu(self, query: np.ndarray) -> SearchResult:
        """CPU fallback using numpy."""
        db = self._db_cpu
        if db is None:
            return SearchResult(
                indices=np.array([], dtype=np.int64),
                scores=np.array([], dtype=np.float32),
                latency_ms=0.0,
            )
        # Cosine similarity (vectors are pre-normalized)
        sims = db @ query
        top_k = min(self.top_k, len(sims))
        # argpartition is O(N) vs O(N log N) for full sort
        if top_k >= len(sims):
            idx = np.argsort(sims)[::-1][:top_k]
        else:
            idx = np.argpartition(sims, -top_k)[-top_k:]
            idx = idx[np.argsort(sims[idx])[::-1]]
        return SearchResult(indices=idx, scores=sims[idx], latency_ms=0.0)

    def _search_torch(self, query: np.ndarray) -> SearchResult:
        """GPU search via PyTorch."""
        import torch
        q = torch.from_numpy(query).cuda()
        # Batched dot product: [N]
        sims = (self._db_gpu @ q).cpu().numpy()
        top_k = min(self.top_k, len(sims))
        idx = np.argpartition(sims, -top_k)[-top_k:]
        idx = idx[np.argsort(sims[idx])[::-1]]
        return SearchResult(indices=idx, scores=sims[idx], latency_ms=0.0)

    def _search_cupy(self, query: np.ndarray) -> SearchResult:
        """GPU search via CuPy."""
        import cupy
        q = cupy.asarray(query)
        sims = self._db_gpu @ q
        sims_np = cupy.asnumpy(sims)
        top_k = min(self.top_k, len(sims_np))
        idx = np.argpartition(sims_np, -top_k)[-top_k:]
        idx = idx[np.argsort(sims_np[idx])[::-1]]
        return SearchResult(indices=idx, scores=sims_np[idx], latency_ms=0.0)


# ---------------------------------------------------------------------------
# GPU batch embedding
# ---------------------------------------------------------------------------

def batch_embed_gpu(phrases: list[str], embed_fn, vectors: np.ndarray | None = None) -> np.ndarray:
    """Embed a batch of phrases, optionally using GPU for normalization.

    If vectors are pre-computed, just normalize on GPU.
    Otherwise, call embed_fn first, then optionally normalize on GPU.

    Args:
        phrases: list of intent phrases
        embed_fn: callable that returns np.ndarray [N, dim]
        vectors: pre-computed vectors (skip embedding step)

    Returns:
        np.ndarray [N, dim] of normalized vectors
    """
    if vectors is None:
        vectors = embed_fn(phrases)

    vectors = np.ascontiguousarray(vectors, dtype=np.float32)
    backend = _detect_backend()

    if backend == "cpu":
        # CPU normalize
        norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10
        return (vectors / norms)

    if backend == "torch":
        import torch
        t = torch.from_numpy(vectors).cuda()
        norms = torch.norm(t, dim=1, keepdim=True) + 1e-10
        t = t / norms
        return t.cpu().numpy()

    if backend == "cupy":
        import cupy
        t = cupy.asarray(vectors)
        norms = cupy.linalg.norm(t, axis=1, keepdims=True) + 1e-10
        t = t / norms
        return cupy.asnumpy(t)

    # Fallback
    norms = np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-10
    return vectors / norms


# ---------------------------------------------------------------------------
# Benchmark
# ---------------------------------------------------------------------------

def benchmark(sizes: list[int] | None = None, dim: int = 384, top_k: int = 3) -> dict:
    """Benchmark GPU vs CPU for vector search at different database sizes.

    Returns dict mapping size → {gpu_ms, cpu_ms, speedup, backend}.
    """
    sizes = sizes or [100, 1_000, 10_000, 100_000]
    results = {}

    # Generate random normalized vectors
    rng = np.random.default_rng(42)
    query = rng.standard_normal(dim).astype(np.float32)
    query /= np.linalg.norm(query)

    for n in sizes:
        db = rng.standard_normal((n, dim)).astype(np.float32)
        norms = np.linalg.norm(db, axis=1, keepdims=True) + 1e-10
        db /= norms

        # CPU benchmark
        searcher_cpu = GPUVectorSearch(dim=dim, top_k=top_k)
        searcher_cpu.backend = "cpu"
        searcher_cpu.load_database(db)
        # Warmup
        searcher_cpu.search(query)
        t0 = time.perf_counter()
        for _ in range(10):
            searcher_cpu.search(query)
        cpu_ms = (time.perf_counter() - t0) / 10 * 1000

        # GPU benchmark
        searcher_gpu = GPUVectorSearch(dim=dim, top_k=top_k)
        gpu_ms = cpu_ms  # default if no GPU
        speedup = 1.0
        if searcher_gpu.backend != "cpu":
            searcher_gpu.load_database(db)
            # Warmup
            searcher_gpu.search(query)
            t0 = time.perf_counter()
            for _ in range(10):
                searcher_gpu.search(query)
            gpu_ms = (time.perf_counter() - t0) / 10 * 1000
            speedup = cpu_ms / gpu_ms if gpu_ms > 0 else float("inf")

        results[n] = {
            "cpu_ms": round(cpu_ms, 3),
            "gpu_ms": round(gpu_ms, 3),
            "speedup": round(speedup, 2),
            "backend": searcher_gpu.backend,
        }
        log.info("Benchmark N=%d: CPU=%.2fms GPU=%.2fms (%s) speedup=%.1fx",
                 n, cpu_ms, gpu_ms, searcher_gpu.backend, speedup)

    return results


def report() -> str:
    """Human-readable status report of the CUDA backend."""
    status = get_status()
    lines = [
        f"Backend: {status.name}",
        f"Device:  {status.device_name}",
    ]
    if status.device_count > 0:
        lines.append(f"GPU count: {status.device_count}")
        lines.append(f"VRAM:     {status.memory_free_mb:.0f} / {status.memory_total_mb:.0f} MB free")
    return "\n".join(lines)
