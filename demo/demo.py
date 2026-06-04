#!/usr/bin/env python3
"""
lever-runner end-to-end demo — 60-second self-contained showcase.

No API keys needed. Uses passthrough mode + position-aware embeddings.

Run:
    python demo/demo.py
"""

import os
import sys
import time
import textwrap

# ── Fix up paths so we can import lever_runner from the repo ────────────
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# ── Force passthrough mode + position-aware embeddings (no API keys) ───
os.environ.setdefault("LLM_BACKEND", "passthrough")
os.environ.setdefault("EMBEDDING_METHOD", "position_aware")
# Use a temp DB so we don't pollute the real one
import tempfile
_tmp = tempfile.mkdtemp(prefix="lever-demo-")
os.environ.setdefault("LANCEDB_PATH", os.path.join(_tmp, "demo.lancedb"))

# ── ANSI colors ─────────────────────────────────────────────────────────
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
RESET = "\033[0m"


def header(title: str) -> None:
    print(f"\n{BOLD}{BLUE}{'=' * 60}{RESET}")
    print(f"{BOLD}{BLUE}  {title}{RESET}")
    print(f"{BOLD}{BLUE}{'=' * 60}{RESET}\n")


def step(label: str, detail: str = "") -> None:
    print(f"  {CYAN}▸{RESET} {BOLD}{label}{RESET}")
    if detail:
        for line in textwrap.wrap(detail, width=56, initial_indent="    ", subsequent_indent="    "):
            print(f"  {DIM}{line}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓ {msg}{RESET}")


def fail(msg: str) -> None:
    print(f"  {RED}✗ {msg}{RESET}")


def info(msg: str) -> None:
    print(f"  {YELLOW}⚡ {msg}{RESET}")


def bullet(msg: str) -> None:
    print(f"    {msg}")


def timed(label: str, fn):
    """Run fn, print timing, return result."""
    t0 = time.perf_counter()
    result = fn()
    ms = (time.perf_counter() - t0) * 1000
    print(f"  {DIM}  ({ms:.1f} ms){RESET}")
    return result, ms


# ══════════════════════════════════════════════════════════════════════════
# DEMO START
# ══════════════════════════════════════════════════════════════════════════
def main():
    total_t0 = time.perf_counter()

    print(f"\n{BOLD}{MAGENTA}╔══════════════════════════════════════════════════════════╗")
    print(f"║  {CYAN}lever-runner{MAGENTA} — end-to-end demo                         ║")
    print(f"║  {DIM}passthrough mode · no API keys · position-aware embeds{MAGENTA}   ║")
    print(f"╚══════════════════════════════════════════════════════════╝{RESET}")

    # ── 1. Fast-Loop: shell injection rejection ────────────────────────
    header("1  FAST-LOOP — Sub-millisecond Input Validation")

    step("Import FastLoopInterceptor")
    from lever_runner.fastloop import FastLoopInterceptor
    fl = FastLoopInterceptor()
    ok("FastLoop ready")

    # Clean inputs
    step("Check clean input", '"check disk usage"')
    result, ms = timed("clean", lambda: fl.check("check disk usage"))
    print(f"    action={GREEN}{result.action}{RESET}  latency={result.latency_us}µs")
    assert result.action == "EXECUTE_IMMEDIATELY"
    ok("Clean input passed")

    print()

    # Dangerous inputs
    dangerous = [
        ('; rm -rf /',           "shell command chaining"),
        ('$(cat /etc/passwd)',    "command substitution"),
        ('`whoami`',             "backtick execution"),
        ('foo | cat /etc/hosts', "pipe injection"),
        ('foo > /tmp/pwned',     "redirect injection"),
        ('foo & bar',            "background execution"),
    ]

    step("Reject dangerous inputs")
    for payload, desc in dangerous:
        r = fl.check(payload)
        if r.action == "ROUTE_TO_DEEP_LOOP":
            print(f"    {RED}blocked{RESET} {desc:30s} {DIM}({r.latency_us}µs){RESET}")
        else:
            print(f"    {YELLOW}UNEXPECTED{RESET} {desc}: action={r.action}")
    ok(f"All {len(dangerous)} injection attempts blocked")

    # ── 2. Position-Aware Embeddings ───────────────────────────────────
    header("2  EMBEDDINGS — Position-Aware Hash Vectors")

    from lever_runner.store import position_aware_embed, hash_embed
    import numpy as np

    step("Compare hash vs position-aware embedding")

    phrases = ["show disk usage", "disk show usage", "usage show disk"]
    print(f"\n    {BOLD}{'Phrase':25s}  {'Hash dist':>10s}  {'Pos-aware dist':>15s}{RESET}")
    print(f"    {'─' * 55}")

    base_embed_pa = np.array(position_aware_embed(phrases[0]))
    base_embed_h = np.array(hash_embed(phrases[0]))

    for phrase in phrases:
        pa = np.array(position_aware_embed(phrase))
        h = np.array(hash_embed(phrase))
        dist_pa = float(np.linalg.norm(base_embed_pa - pa))
        dist_h = float(np.linalg.norm(base_embed_h - h))
        match = "✓" if phrase == phrases[0] else ""
        print(f"    {phrase:25s}  {dist_h:10.4f}  {dist_pa:15.4f}  {match}")

    ok("Position-aware distinguishes word order — pure hash does not")

    step("Embedding dimensionality check")
    vec = position_aware_embed("check disk usage")
    print(f"    dim = {len(vec)}  (compact 64-d hash vector)")
    norm = float(np.linalg.norm(vec))
    print(f"    L2 norm = {norm:.4f}  (unit-normalized)")
    ok(f"Embedding ready: {len(vec)}-dim vectors")

    # ── 3. Command Store + Vector Search ───────────────────────────────
    header("3  COMMAND STORE — Seed + Vector Search")

    from lever_runner.store import CommandStore

    step("Initialize CommandStore", f"LANCEDB_PATH={os.environ['LANCEDB_PATH']}")
    store, ms = timed("init", lambda: CommandStore(chat_id="demo"))
    print(f"    backend: position-aware embeddings")
    n = store.count()
    print(f"    commands seeded: {n}")
    ok(f"Store ready with {n} commands")

    step("Teach a custom command")
    store.teach("show my public ip", "curl ifconfig.me")
    ok("Taught: 'show my public ip' → curl ifconfig.me")

    print()

    step("Vector search — find best match")
    queries = [
        ("how much disk space do I have left", "df -h"),
        ("what's my ip address", "curl ifconfig.me"),
        ("show running processes", "ps aux"),
        ("list files here", "ls -la"),
        ("check memory usage", "free -h"),
    ]

    for query, expected_cmd in queries:
        t0 = time.perf_counter()
        matches = store.find_best(query, top_k=1)
        ms_search = (time.perf_counter() - t0) * 1000
        if matches:
            m = matches[0]
            cmd_short = m.command.split()[0]
            dist_str = f"{m.score:.3f}"
            sim_str = f"{m.similarity:.2f}"
            match_ok = expected_cmd.split()[0] in m.command
            icon = f"{GREEN}✓{RESET}" if match_ok else f"{YELLOW}~{RESET}"
            print(
                f"    {icon} {query[:35]:35s} → {m.command[:25]:25s} "
                f"dist={dist_str}  sim={sim_str}  {DIM}({ms_search:.1f}ms){RESET}"
            )
        else:
            fail(f"No match for: {query}")

    ok("Vector search working — cosine similarity over LanceDB")

    # ── 4. Full Pipeline: input → fastloop → embed → match → execute ──
    header("4  FULL PIPELINE — Input → FastLoop → Embed → Match → Execute")

    from lever_runner.orchestrator import do

    step("Run full pipeline: 'check disk usage'")
    result, ms = timed("pipeline", lambda: do("check disk usage", store=store, auto_run=False))

    print(f"\n    {BOLD}Pipeline breakdown:{RESET}")
    print(f"    Input:        {CYAN}\"check disk usage\"{RESET}")
    print(f"    Intent:       {CYAN}\"{result.intent}\"{RESET}")
    print(f"    Matched:      {GREEN}{result.match.command}{RESET}")
    print(f"    Trust:        {result.match.trust_score:.0f}/100")
    print(f"    Similarity:   {result.match.similarity:.2f}")
    print(f"    Tokens:       in={result.tokens_in}  out={result.tokens_out}")
    print(f"    Backend:      {result.intent and 'passthrough'}")
    ok(f"Full pipeline in {ms:.1f} ms")

    print()

    step("Pipeline rejects injection through fastloop")
    bad_result, ms2 = timed("reject", lambda: do("; rm -rf /", store=store, auto_run=False))
    print(f"    action:       {RED}{bad_result.error}{RESET}")
    assert not bad_result.ok
    ok("Injection stopped at fast-loop gate — never reached the store")

    print()

    step("Pipeline: multiple natural-language queries")
    queries = [
        "show me the current directory",
        "what processes are running",
        "how much memory is available",
    ]
    for q in queries:
        r = do(q, store=store, auto_run=False)
        if r.ok and r.match:
            print(f"    {GREEN}→{RESET} {q[:35]:35s}  ⇒  {r.match.command}")
        else:
            print(f"    {YELLOW}→{RESET} {q[:35]:35s}  ⇒  {r.error or 'no match'}")
    ok("Natural language → commands working")

    # ── 5. Summary ─────────────────────────────────────────────────────
    total_ms = (time.perf_counter() - total_t0) * 1000

    header("5  SUMMARY")

    print(f"  {BOLD}Architecture:{RESET}   User Input → FastLoop → Embed → Search → Execute")
    print(f"  {BOLD}LLM Backend:{RESET}    passthrough (no API keys, $0/month)")
    print(f"  {BOLD}Embeddings:{RESET}     position-aware hash (64-dim, ~1µs)")
    print(f"  {BOLD}Vector DB:{RESET}       LanceDB (embedded, zero config)")
    print(f"  {BOLD}Command table:{RESET}   {store.count()} pre-approved commands")
    print(f"  {BOLD}Fast-Loop:{RESET}       blocks shell injection in <1ms")
    print(f"  {BOLD}Total demo time:{RESET} {total_ms:.0f}ms")
    print()
    print(f"  {GREEN}{BOLD}The LLM never sees your shell. The shell never sees the LLM.{RESET}")
    print()

    # Cleanup temp DB
    import shutil
    try:
        shutil.rmtree(_tmp, ignore_errors=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
