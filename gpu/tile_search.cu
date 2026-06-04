// tile_search.cu — CUDA kernels for lever-runner GPU acceleration
//
// Compiled to tile_search.so via: make
// Provides cosine similarity search and vector normalization on GPU.
//
// Build:
//   nvcc -shared -Xcompiler -fPIC -o tile_search.so tile_search.cu \
//        -arch=sm_75 -O3
//
// Usage from Python (ctypes):
//   lib = ctypes.CDLL("./tile_search.so")
//   lib.cosine_search(...)

#include <cmath>
#include <cstdio>

// ---------------------------------------------------------------------------
// cosine_search — compute cosine similarity between a query and N database vectors
//
// Assumes vectors are pre-normalized to unit length.
// Each thread handles one database vector.
// ---------------------------------------------------------------------------

extern "C" __global__ void cosine_search(
    const float* __restrict__ query,     // [dim]
    const float* __restrict__ database,  // [N * dim] row-major
    float* __restrict__ scores,          // [N] output
    int N,
    int dim
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;

    float dot = 0.0f;
    const float* vec = database + idx * dim;
    for (int d = 0; d < dim; d++) {
        dot += query[d] * vec[d];
    }
    scores[idx] = dot;
}

// ---------------------------------------------------------------------------
// batch_normalize — normalize N vectors to unit length in-place
// ---------------------------------------------------------------------------

extern "C" __global__ void batch_normalize(
    float* __restrict__ vectors,  // [N * dim] row-major
    int N,
    int dim
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;

    float sum_sq = 0.0f;
    float* vec = vectors + idx * dim;
    for (int d = 0; d < dim; d++) {
        float v = vec[d];
        sum_sq += v * v;
    }
    float inv_norm = 1.0f / (sqrtf(sum_sq) + 1e-10f);
    for (int d = 0; d < dim; d++) {
        vec[d] *= inv_norm;
    }
}

// ---------------------------------------------------------------------------
// batch_embed_normalize — embed + normalize in one pass
//
// Takes raw embedding output (from sentence-transformers) and normalizes
// each vector. Useful as a post-processing step after CPU embedding.
// ---------------------------------------------------------------------------

extern "C" __global__ void batch_embed_normalize(
    float* __restrict__ vectors,  // [N * dim] row-major
    int N,
    int dim
) {
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= N) return;

    float sum_sq = 0.0f;
    float* vec = vectors + idx * dim;
    for (int d = 0; d < dim; d++) {
        float v = vec[d];
        sum_sq += v * v;
    }
    float inv_norm = 1.0f / (sqrtf(sum_sq) + 1e-10f);
    for (int d = 0; d < dim; d++) {
        vec[d] *= inv_norm;
    }
}

// ---------------------------------------------------------------------------
// C API wrappers for ctypes access
// ---------------------------------------------------------------------------

extern "C" {

// Launch cosine_search kernel
void launch_cosine_search(
    const float* query,
    const float* database,
    float* scores,
    int N,
    int dim,
    void* stream  // cudaStream_t, can be nullptr
) {
    int block = 256;
    int grid = (N + block - 1) / block;
    cosine_search<<<grid, block, 0, (cudaStream_t)stream>>>(
        query, database, scores, N, dim
    );
}

// Launch batch_normalize kernel
void launch_batch_normalize(
    float* vectors,
    int N,
    int dim,
    void* stream
) {
    int block = 256;
    int grid = (N + block - 1) / block;
    batch_normalize<<<grid, block, 0, (cudaStream_t)stream>>>(
        vectors, N, dim
    );
}

} // extern "C"
