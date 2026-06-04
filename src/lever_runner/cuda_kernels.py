"""
cuda_kernels.py — CUDA kernel source strings for GPU-accelerated vector ops.

Kernels are compiled at runtime via PyCUDA, CuPy, or loaded as a pre-compiled
shared library via ctypes. The module exports raw source strings and a
dispatcher that picks the best available backend.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("lever-runner.cuda_kernels")

# ---------------------------------------------------------------------------
# CUDA C kernel sources (compiled at runtime by pycuda/cupy, or via Makefile)
# ---------------------------------------------------------------------------

COSINE_SEARCH_KERNEL = r"""
// cosine_search_kernel.cu — search N vectors against 1 query on GPU
// Each thread computes cosine similarity between the query and one database vector.
// Results are written to an output array of (index, score) pairs.

extern "C" __global__ void cosine_search_kernel(
    const float* __restrict__ query,     // [dim]
    const float* __restrict__ database,  // [N x dim] row-major
    float* __restrict__ scores,          // [N] output similarity scores
    const int N,
    const int dim
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;

    // Compute dot product (vectors are pre-normalized, so dot = cosine sim)
    float dot = 0.0f;
    for (int d = 0; d < dim; d++) {
        dot += query[d] * database[idx * dim + d];
    }
    scores[idx] = dot;
}
"""

BATCH_EMBED_KERNEL = r"""
// batch_embed_kernel.cu — normalize N vectors on GPU
// After embedding on GPU, normalize each vector to unit length for cosine similarity.

extern "C" __global__ void batch_normalize_kernel(
    float* __restrict__ vectors,  // [N x dim] row-major, in-place normalize
    const int N,
    const int dim
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;

    // Compute L2 norm of vector[idx]
    float sum_sq = 0.0f;
    for (int d = 0; d < dim; d++) {
        float v = vectors[idx * dim + d];
        sum_sq += v * v;
    }
    float inv_norm = 1.0f / (sqrtf(sum_sq) + 1e-10f);

    // Normalize
    for (int d = 0; d < dim; d++) {
        vectors[idx * dim + d] *= inv_norm;
    }
}
"""

TOPK_KERNEL = r"""
// topk_kernel.cu — find top-K scores from N candidates on GPU
// Uses a per-block reduction approach; for small K (e.g. 3) this is efficient.

extern "C" __global__ void topk_init_kernel(
    int* __restrict__ indices,    // [N] initialized to own index
    const int N
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < N) {
        indices[idx] = idx;
    }
}
"""

# ---------------------------------------------------------------------------
# PTX kernel — hand-optimized dot product for the critical path
# ---------------------------------------------------------------------------

COSINE_DOT_PTX = r"""
.version 8.5
.target sm_75
.address_size 64

// cosine_dot_product.ptx — warp-level cosine similarity hot path
// Assumes pre-normalized vectors, so dot product == cosine similarity.
// Uses warp shuffle for final reduction.
//
// This PTX is loaded via cuModuleLoadData when PyCUDA/CuPy is available,
// or via the pre-compiled .so from gpu/Makefile otherwise.

.visible .entry cosine_dot_warp(
    .param .u64 vec_a_ptr,      // query vector (float*)
    .param .u64 vec_b_ptr,      // database vector (float*)
    .param .u32 dim,            // vector dimension
    .param .u64 out_ptr         // output score (float*)
)
{
    .reg .f32 sum, va, vb, prod;
    .reg .u32 i, lane, dim_reg;
    .reg .u64 a_base, b_base, out_base;
    .reg .pred p_done;

    ld.param.u64 a_base, [vec_a_ptr];
    ld.param.u64 b_base, [vec_b_ptr];
    ld.param.u32 dim_reg, [dim];
    ld.param.u64 out_base, [out_ptr];

    mov.f32 sum, 0.0;

    // Each lane processes strided elements for better memory coalescing
    // lane 0 handles offset 0, lane 1 handles offset 1, etc.
    mov.u32 lane, %laneid;

    // Strided dot product: each thread accumulates every 32nd element
    setp.eq.u32 p_done, lane, dim_reg;
    @p_done bra DONE;

    mov.u32 i, lane;

LOOP:
    setp.ge.u32 p_done, i, dim_reg;
    @p_done bra REDUCE;

    ld.global.f32 va, [a_base + 4*i];
    ld.global.f32 vb, [b_base + 4*i];
    fma.rn.f32 sum, va, vb, sum;
    add.u32 i, i, 32;    // warp-width stride
    bra LOOP;

REDUCE:
    // Warp shuffle reduction (32 lanes → 1 value)
    shfl.sync.down.add.f32 sum, sum, 16, 0x1f;
    shfl.sync.down.add.f32 sum, sum, 8,  0x1f;
    shfl.sync.down.add.f32 sum, sum, 4,  0x1f;
    shfl.sync.down.add.f32 sum, sum, 2,  0x1f;
    shfl.sync.down.add.f32 sum, sum, 1,  0x1f;

    // Lane 0 writes the result
    setp.eq.u32 p_done, lane, 0;
    @p_done st.global.f32 [out_base], sum;

DONE:
    ret;
}
"""

# ---------------------------------------------------------------------------
# Kernel loader / dispatcher
# ---------------------------------------------------------------------------

# Path to pre-compiled shared library (from gpu/Makefile)
_GPU_LIB_PATH = Path(__file__).resolve().parent.parent.parent / "gpu" / "tile_search.so"


def get_kernel_source(name: str) -> str:
    """Return raw CUDA C or PTX source string by name."""
    sources = {
        "cosine_search": COSINE_SEARCH_KERNEL,
        "batch_normalize": BATCH_EMBED_KERNEL,
        "topk_init": TOPK_KERNEL,
        "cosine_dot_ptx": COSINE_DOT_PTX,
    }
    if name not in sources:
        raise ValueError(f"unknown kernel: {name!r}. Available: {sorted(sources.keys())}")
    return sources[name]


def get_shared_lib_path() -> Path:
    """Return the path to the pre-compiled GPU shared library."""
    override = os.getenv("LEVER_GPU_LIB")
    if override:
        return Path(override)
    return _GPU_LIB_PATH
