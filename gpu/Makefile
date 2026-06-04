# gpu/Makefile — compile CUDA kernels to shared library for lever-runner
#
# Targets:
#   make          — build tile_search.so
#   make ptx      — assemble PTX into an object file
#   make clean    — remove build artifacts
#   make test     — quick smoke test
#
# Requirements:
#   - NVIDIA CUDA Toolkit (nvcc on PATH)
#   - SM capability >= 75 (Turing+; override with SM=<arch>)
#
# The produced tile_search.so is loaded by cuda_backend.py via ctypes
# as a last-resort GPU backend (after torch/cupy/pycuda).

NVCC   ?= nvcc
SM     ?= sm_75
LIB    := tile_search.so
PTX_OBJ := tile_search_ptx.o
SRC    := tile_search.cu
PTX    := tile_search.ptx

NVCC_FLAGS := -shared -Xcompiler -fPIC -O3 -arch=$(SM) \
              --generate-line-info \
              -Xptxas -v

.PHONY: all ptx clean test

all: $(LIB)

$(LIB): $(SRC)
	$(NVCC) $(NVCC_FLAGS) -o $@ $<
	@echo "Built $@ ($(SM))"

# Assemble hand-written PTX into a linkable object
ptx: $(PTX_OBJ)

$(PTX_OBJ): $(PTX)
	ptxas -arch=$(SM) -o $@ $<
	@echo "Assembled $@ from PTX"

clean:
	rm -f $(LIB) $(PTX_OBJ) *.o

# Smoke test: compile and verify the .so loads
test: $(LIB)
	@python3 -c "\
import ctypes, sys; \
lib = ctypes.CDLL('./$(LIB)'); \
print('OK: tile_search.so loaded'); \
print('  launch_cosine_search:', hasattr(lib, 'launch_cosine_search')); \
print('  launch_batch_normalize:', hasattr(lib, 'launch_batch_normalize')); \
"
