"""
doctor.py — `lever-runner doctor`.

Pre-flight check for the operator: validates config, env, DB, and
each LLM backend's reachability. Prints a checklist with PASS/WARN/FAIL
per item and exits non-zero on any FAIL.

Run with:
    python -m lever_runner.doctor
    lever-runner-doctor    (if installed)
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import Callable

from dotenv import load_dotenv

# Lazy imports inside _check_* functions so a missing optional dep
# doesn't make the whole doctor fail before we even get to print.

OK = "PASS"
WARN = "WARN"
FAIL = "FAIL"


def _check(label: str, ok: bool, detail: str = "", level: str = OK) -> tuple[str, str, str]:
    return (label, level, detail if not ok else (detail or "ok"))


def check_python() -> tuple[str, str, str]:
    v = sys.version_info
    if v.major == 3 and v.minor >= 10:
        return _check("python version", True, f"{v.major}.{v.minor}.{v.micro}")
    return _check("python version", False,
                  f"need 3.10+, got {v.major}.{v.minor}.{v.micro}", FAIL)


def check_lancedb() -> tuple[str, str, str]:
    try:
        import lancedb  # noqa: F401
        return _check("lancedb importable", True)
    except ImportError as e:
        return _check("lancedb importable", False, str(e), FAIL)


def check_telegram_token() -> tuple[str, str, str]:
    tok = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not tok:
        return _check("TELEGRAM_BOT_TOKEN", False, "unset", FAIL)
    # Telegram bot tokens are 35 chars: <bot_id>:<35-char-secret>
    if ":" not in tok or len(tok.split(":", 1)[1]) < 30:
        return _check("TELEGRAM_BOT_TOKEN", False, "looks malformed", FAIL)
    return _check("TELEGRAM_BOT_TOKEN", True, "set, format ok")


def check_allowed_user() -> tuple[str, str, str]:
    uid = os.getenv("ALLOWED_USER_ID", "").strip()
    if not uid:
        return _check("ALLOWED_USER_ID", True, "unset (bot is open to anyone)", WARN)
    if not uid.isdigit():
        return _check("ALLOWED_USER_ID", False, "not a numeric Telegram id", FAIL)
    return _check("ALLOWED_USER_ID", True, f"locked to uid={uid}")


def check_db_path() -> tuple[str, str, str]:
    path = os.getenv("LANCEDB_PATH", "./data/lever.lancedb")
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    if not os.path.exists(path):
        return _check("lancedb path", True,
                      f"{path} (does not exist; will be created on first run)", WARN)
    # Try opening it
    try:
        import lancedb
        db = lancedb.connect(path)
        tables = db.list_tables().tables
        return _check("lancedb path", True, f"{path} (tables: {sorted(tables)})")
    except Exception as e:
        return _check("lancedb path", False, f"{path}: {e}", FAIL)


def check_sandbox_path() -> tuple[str, str, str]:
    path = os.getenv("SANDBOX_ROOT", "/tmp/lever-runner")
    if not os.path.isabs(path):
        return _check("sandbox root", False, f"{path} (must be absolute)", FAIL)
    try:
        os.makedirs(path, exist_ok=True)
        test = os.path.join(path, ".doctor_write_test")
        with open(test, "w") as f:
            f.write("ok")
        os.remove(test)
        return _check("sandbox root", True, f"{path} (writable)")
    except Exception as e:
        return _check("sandbox root", False, f"{path}: {e}", FAIL)


def check_llm_backend() -> tuple[str, str, str]:
    """Check the configured LLM backend is reachable."""
    backend = os.getenv("LLM_BACKEND", "passthrough").strip().lower()
    if backend == "passthrough":
        return _check("LLM_BACKEND", True, "passthrough (no LLM call; cheaper but lower quality)")
    if backend == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        try:
            import requests
            r = requests.get(f"{host}/api/tags", timeout=3)
            r.raise_for_status()
            return _check("LLM_BACKEND", True, f"{backend} -> {host} (reachable)")
        except Exception as e:
            return _check("LLM_BACKEND", False, f"{backend} -> {host}: {e}", FAIL)
    # Hosted: just check the env var is set
    keymap = {
        "minimax": "MINIMAX_API_KEY",
        "openai": "OPENAI_API_KEY",
        "deepinfra": "DEEPINFRA_API_KEY",
    }
    key_env = keymap.get(backend, "LLM_API_KEY")
    if not os.getenv(key_env) and not os.getenv("LLM_API_KEY"):
        return _check("LLM_BACKEND", False,
                      f"{backend}: no key in {key_env} or LLM_API_KEY", FAIL)
    return _check("LLM_BACKEND", True, f"{backend} (key set)")


def check_fallbacks() -> tuple[str, str, str]:
    chain = os.getenv("LLM_FALLBACKS", "deepinfra").strip()
    if not chain:
        return _check("LLM_FALLBACKS", True, "unset (no fallbacks; passthrough is the last resort)", WARN)
    items = [c.strip() for c in chain.split(",") if c.strip()]
    primary = os.getenv("LLM_BACKEND", "passthrough").strip().lower()
    if primary in items:
        return _check("LLM_FALLBACKS", False,
                      f"primary {primary!r} is also in fallback chain; will be tried twice", WARN)
    return _check("LLM_FALLBACKS", True, f"{primary} -> {items} -> passthrough")


def check_log_dir() -> tuple[str, str, str]:
    """Verify the directory holding token_usage.jsonl and embed_usage.jsonl is writable."""
    tok_path = os.getenv("TOKEN_LOG_PATH", "./data/token_usage.jsonl")
    embed_path = os.getenv("EMBED_LOG_PATH", "./data/embed_usage.jsonl")
    paths = [tok_path, embed_path]
    if not paths:
        return _check("log paths", True, "no log paths set")
    for p in paths:
        d = os.path.dirname(p) or "."
        if not os.path.isabs(d):
            d = os.path.abspath(d)
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".doctor_log_test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
        except Exception as e:
            return _check("log paths", False, f"{d}: {e}", FAIL)
    return _check("log paths", True, f"token={tok_path} embed={embed_path}")


def check_disk_space() -> tuple[str, str, str]:
    """Warn if less than 1GB free on the lancedb path's filesystem."""
    import shutil
    db = os.getenv("LANCEDB_PATH", "./data/lever.lancedb")
    if not os.path.isabs(db):
        db = os.path.abspath(db)
    if not os.path.exists(db):
        db = os.path.dirname(db) or "."
    try:
        usage = shutil.disk_usage(db)
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 1.0:
            return _check("disk space", False, f"{free_gb:.2f} GB free on {db}", FAIL)
        if free_gb < 5.0:
            return _check("disk space", True, f"{free_gb:.2f} GB free on {db}", WARN)
        return _check("disk space", True, f"{free_gb:.1f} GB free on {db}")
    except Exception as e:
        return _check("disk space", True, f"could not check: {e}", WARN)


def check_smoke() -> tuple[str, str, str]:
    """Run a tiny in-process smoke (no LLM call) to verify DB+embedder wiring."""
    try:
        from .store import CommandStore
        s = CommandStore(chat_id="_doctor_test")
        s.count()
        return _check("in-process smoke", True, f"DB ok, {s.count()} rows in _doctor_test")
    except Exception as e:
        return _check("in-process smoke", False, str(e), FAIL)


CHECKS: list[Callable[[], tuple[str, str, str]]] = [
    check_python,
    check_lancedb,
    check_telegram_token,
    check_allowed_user,
    check_db_path,
    check_sandbox_path,
    check_llm_backend,
    check_fallbacks,
    check_log_dir,
    check_disk_space,
    check_smoke,
]


def main() -> int:
    load_dotenv()
    print(f"lever-runner doctor @ {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
    fails = 0
    warns = 0
    for fn in CHECKS:
        try:
            label, level, detail = fn()
        except Exception as e:
            label, level, detail = fn.__name__, FAIL, f"crashed: {e}"
        marker = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}[level]
        print(f"  [{marker}] {label}")
        if detail and detail != "ok":
            print(f"      {detail}")
        if level == FAIL:
            fails += 1
        elif level == WARN:
            warns += 1
    print()
    if fails:
        print(f"doctor: {fails} failure(s), {warns} warning(s). Fix the failures above and re-run.")
        return 1
    if warns:
        print(f"doctor: ok with {warns} warning(s). Bot will run but review the warnings.")
    else:
        print("doctor: all checks pass. Bot is ready to start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
