# Future Integration: lever-runner

## Current State
The trust compiler — teach once, run forever. A command-matching engine where the LLM never sees your shell. Three-gate pipeline: exact hash match → vector similarity → keyword fallback. 160 tests, PyPI published. Runs with $0/month in passthrough mode (no API keys needed).

## Integration Opportunities

### With room-as-codespace demo product
lever-runner IS the demo product for the room-as-codespace vision. Imagine: "teach your room once, run it forever." A room's ensign learns commands (how to query its cells, how to trigger evolution, how to report anomalies) and executes them forever without LLM calls. The trust compiler pattern — teach locally, execute deterministically — is exactly how rooms should work.

### With construct-core
lever-runner's three-gate pipeline maps to construct-core's layered traits: Gate 1 (exact hash) = Layer 0 BareMetalConstruct lookup, Gate 2 (vector similarity) = Layer 1 SyncConstruct query, Gate 3 (keyword fallback) = Layer 2 AsyncConstruct external call. Each gate is a more expensive fallback, matching construct-core's tier system.

### With position-aware-embed
lever-runner's Gate 2 uses position-aware-embed for fuzzy matching. This is already integrated. The next step: ternary-encode the embeddings so that similar ternary strategies have similar vectors, enabling strategy search via the same pipeline.

## Dormant Ideas Now Unlockable
The teach-once-run-forever model was for shell commands. Now it applies to room skills: teach a room how to handle a sensor pattern once, and it handles it forever without LLM calls. The trust compiler scales from shell commands to room behaviors.

## Potential in Mature Systems
Every room has lever-runner embedded. When an ensign encounters a new situation, it "teaches" the room the appropriate response (via LLM). Thereafter, the response is executed deterministically via the three-gate pipeline — no LLM, no latency, no cost. Rooms get smarter over time without getting more expensive.

## Cross-Pollination Ideas
- **lever-runner-carapace**: Rust acceleration layer for the three-gate pipeline
- **lever-runner-wasm**: Browser-based room control via WASM
- **fastloop-guard**: Guard's LLM cache complements lever-runner's command cache

## Dependencies for Next Steps
- Extend teach/learn to room behaviors beyond shell commands
- Ternary strategy embeddings for Gate 2 similarity matching
- Integration with room's tick cycle for automatic teaching
