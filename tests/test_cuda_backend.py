"""Test CUDA backend — works with and without GPU."""

from __future__ import annotations

import numpy as np
import pytest

from lever_runner.cuda_backend import (
    GPUVectorSearch,
    batch_embed_gpu,
    benchmark,
    get_status,
    report,
    _detect_backend,
)
from lever_runner.cuda_kernels import get_kernel_source, get_shared_lib_path


class TestCUDAKernels:
    """Kernel source strings should be loadable."""

    def test_cosine_search_source(self):
        src = get_kernel_source("cosine_search")
        assert "cosine_search_kernel" in src
        assert "__global__" in src

    def test_batch_normalize_source(self):
        src = get_kernel_source("batch_normalize")
        assert "batch_normalize_kernel" in src

    def test_ptx_source(self):
        src = get_kernel_source("cosine_dot_ptx")
        assert ".target sm_75" in src
        assert "shfl.sync" in src

    def test_unknown_kernel_raises(self):
        with pytest.raises(ValueError, match="unknown kernel"):
            get_kernel_source("nonexistent")

    def test_shared_lib_path(self):
        path = get_shared_lib_path()
        assert path.name == "tile_search.so"


class TestBackendDetection:
    """Backend detection should work on any machine."""

    def test_returns_valid_backend(self):
        backend = _detect_backend()
        assert backend in ("torch", "cupy", "pycuda", "ctypes", "cpu")

    def test_status_report(self):
        status = get_status()
        assert status.name in ("torch", "cupy", "pycuda", "ctypes", "cpu")
        assert isinstance(status.device_name, str)

    def test_report_string(self):
        r = report()
        assert "Backend:" in r


class TestGPUVectorSearch:
    """GPUVectorSearch should work on CPU at minimum."""

    def test_search_cpu(self):
        rng = np.random.default_rng(42)
        dim = 64
        db = rng.standard_normal((100, dim)).astype(np.float32)
        norms = np.linalg.norm(db, axis=1, keepdims=True) + 1e-10
        db /= norms

        query = db[0].copy()  # exact match for first vector

        searcher = GPUVectorSearch(dim=dim, top_k=3)
        searcher.backend = "cpu"
        searcher.load_database(db)

        result = searcher.search(query)
        assert result.indices[0] == 0
        assert result.scores[0] > 0.99
        assert result.latency_ms >= 0

    def test_search_empty(self):
        searcher = GPUVectorSearch(dim=384, top_k=3)
        searcher.backend = "cpu"
        # No database loaded
        result = searcher.search(np.zeros(384, dtype=np.float32))
        assert len(result.indices) == 0

    def test_is_gpu_flag(self):
        searcher = GPUVectorSearch(dim=384)
        # On a machine without GPU, this should be False
        backend = _detect_backend()
        assert searcher.is_gpu == (backend != "cpu")


class TestBatchEmbed:
    """batch_embed_gpu should normalize vectors."""

    def test_normalize_cpu(self):
        rng = np.random.default_rng(42)
        vectors = rng.standard_normal((10, 64)).astype(np.float32)
        result = batch_embed_gpu([], embed_fn=None, vectors=vectors)
        norms = np.linalg.norm(result, axis=1)
        np.testing.assert_allclose(norms, 1.0, atol=1e-5)


class TestBenchmark:
    """Quick benchmark with small sizes."""

    def test_small_benchmark(self):
        results = benchmark(sizes=[10, 100], dim=64, top_k=3)
        assert 10 in results
        assert 100 in results
        assert results[10]["cpu_ms"] > 0
        assert "speedup" in results[10]
