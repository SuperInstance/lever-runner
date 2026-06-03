# Show HN: I built a shell AI where prompt injection is physically impossible

Most AI shell agents work by stuffing tool schemas into every prompt and letting the LLM generate shell commands. That means 1,500–10,000 tokens per turn ($5–$200 per 1K turns) and a fundamental attack surface: if you can manipulate the LLM, you can execute arbitrary code.

I built lever-runner around a different model: the LLM never sees the shell, never generates commands, and has zero knowledge of what's being executed.

**How it works:**

1. LLM compresses the user request into a 3–8 word intent phrase (~60 tokens in, ~8 out)
2. A local embedding model (all-MiniLM-L6-v2, ~80MB, runs on CPU) converts the phrase to a vector
3. LanceDB matches the vector against a table of pre-approved commands by cosine similarity
4. The closest match executes in a sandbox with a 30s timeout

If nothing clears the similarity floor (0.55), nothing runs. The LLM cannot output a shell command — it can only emit a phrase that gets matched against known-good commands.

**Token numbers from the benchmark (20-task suite):**

- Passthrough mode (no LLM): ~6.3 tokens/command, $0/1K commands
- Hosted LLM (Llama 3.1 8B): ~76 tokens/command, $0.002/1K commands
- OpenAI function calling: 1,500–8,000 tokens/command, $5–$50/1K commands

95–99% token reduction. The blast radius of a hostile prompt is "the wrong pre-approved command ran once and lost 4.0 trust points."

Ships with 66 seed commands (git, docker, npm, systemd, networking). Add new ones with a single `/teach` message. Trust-scored, self-improving (hourly cron promotes high-trust commands, flags failing ones).

GitHub: https://github.com/SuperInstance/lever-runner
Benchmark script: https://github.com/SuperInstance/lever-runner/blob/main/src/lever_runner/benchmark.py

MIT licensed, ~2K lines of Python, no framework lock-in.

Happy to answer questions about the architecture.
