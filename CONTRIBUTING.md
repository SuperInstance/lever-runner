# Contributing to Lever-Runner

Thanks for your interest! Here's how to contribute.

## Quick Start

```bash
git clone https://github.com/SuperInstance/lever-runner && cd lever-runner
pip install -e ".[dev]"
python -m pytest tests/ -v
```

All 160+ tests should pass in under 10 seconds.

## How to Add Skill Packs

Skill packs are JSONL files containing command entries. Each line is a JSON object:

```json
{"phrase": "show disk usage", "command": "df -h", "trust": 80}
```

To create a skill pack:

1. **Use lever-runner interactively.** Teach commands with `python -m lever_runner teach "phrase" --command "cmd"`.
2. **Export your database:** `python -m lever_runner.export > my-skillpack.jsonl`
3. **Add metadata.** Create a `skillpack.json` with name, description, author, and command count.
4. **Submit a PR** with both files to [lever-runner-skills](https://github.com/SuperInstance/lever-runner-skills).

### Parameterized Commands

Use `{{param}}` templates for commands that take arguments:

```json
{"phrase": "show logs for {{container}}", "command": "docker logs --tail 100 {{container}}", "trust": 70}
```

Arguments are validated at execution time. Shell metacharacters (`;`, `|`, `&`, `$`, backticks, etc.) are blocked.

### Skill Pack Guidelines

- **One topic per pack.** DevOps, git, databases, cloud, etc.
- **Include variations.** "show disk usage", "check disk space", "how much disk left" — more phrases = better matching.
- **Start trust at 70-80.** The auto-promote system will adjust over time.
- **Test locally first.** `python -m lever_runner.import my-skillpack.jsonl && python -m lever_runner "your test phrase"`

## How to Add LLM Backends

Lever-runner supports multiple LLM backends for intent extraction. To add a new one:

1. **Create a backend module** in `src/lever_runner/`. Follow the pattern in `intent_extractor.py`.
2. **Implement the interface:** Your backend must accept a user request string and return a short intent phrase (3-8 words).
3. **Add to the fallback chain.** Update `orchestrator.py` to include your backend in the `LLM_FALLBACKS` resolution.
4. **Add environment variables.** Follow the naming convention: `LLM_<NAME>_BASE_URL`, `LLM_<NAME>_MODEL`.
5. **Write tests.** Add `tests/test_<backend>.py` with at least:
   - Happy path (valid key, returns phrase)
   - Missing key (falls through to next backend)
   - Timeout (falls through gracefully)
   - Malformed response (falls through gracefully)
6. **Update README.** Add your backend to the comparison table and usage examples.

### Backend Checklist

- [ ] Implements `extract_intent(request: str) -> str`
- [ ] Respects `LLM_TIMEOUT_SEC`
- [ ] Falls through on 4xx/5xx/timeout (doesn't hang)
- [ ] Key resolution: `LLM_API_KEY` → `LLM_<NAME>_API_KEY` → `LLM_<NAME>_KEY`
- [ ] No secrets in logs or prompts
- [ ] Tests cover happy path + 3 failure modes

## How to Run Tests

```bash
# All tests
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_params.py -v

# Quick smoke test
python -m pytest tests/smoke.py -v

# With coverage
python -m pytest tests/ --cov=lever_runner --cov-report=term-missing
```

### Test Structure

- `tests/test_params.py` — Parameterized command tests (slot filling, validation)
- `tests/test_embeddings.py` — Embedding pipeline and vector search
- `tests/test_three_gate.py` — Three-gate architecture integration
- `tests/test_fastloop.py` — Fastloop guard integration
- `tests/test_fastloop_bridge.py` — Rust-Python bridge
- `tests/test_bot.py` — Telegram bot handlers
- `tests/test_export_nail.py` — pincherOS export bridge
- `tests/smoke.py` — End-to-end smoke test

## How to Report Issues

**Bug reports:**

1. Check [existing issues](https://github.com/SuperInstance/lever-runner/issues) first.
2. Include: Python version, OS, `LLM_BACKEND`, and the exact command that failed.
3. Run `lever-runner-doctor` and include the output.

**Feature requests:**

1. Describe the use case, not just the feature.
2. Explain how it fits the post-inference architecture (LLM produces phrase, not shell).
3. If it requires the LLM to see shell commands, it probably doesn't fit — explain why the exception is warranted.

## Architecture Notes

```
src/lever_runner/
├── __main__.py       # Entry point
├── cli.py            # CLI interface
├── orchestrator.py   # Core: request → intent → match → execute
├── intent_extractor.py  # LLM backend abstraction
├── store.py          # LanceDB command store
├── executor.py       # Sandboxed command execution
├── bot.py            # Telegram bot
├── http_api.py       # HTTP API server
├── doctor.py         # Diagnostic tool
├── fastloop.py       # Three-gate fast loop
├── fastloop_bridge.py # Rust guard bridge
├── benchmark.py      # Performance benchmarking
├── token_logger.py   # Token usage tracking
├── auto_promote.py   # Trust score management
├── seed_export.py    # Export commands to JSONL
├── seed_import.py    # Import commands from JSONL
├── export_nail.py    # pincherOS .nail export
└── init_db.py        # Database initialization
```

The golden rule: **the LLM never sees a shell command.** It produces a phrase; we look up a pre-approved command. If your contribution breaks this invariant, it needs a very good reason.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
