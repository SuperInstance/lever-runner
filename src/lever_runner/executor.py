"""
executor.py — run a pre-approved command in a per-session sandbox.

The LLM never knows this module exists. We just chdir into a per-session
scratch dir, run the command with a hard timeout, and capture stdout/stderr.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

SANDBOX_ROOT = Path(os.getenv("SANDBOX_ROOT", "/tmp/lever-runner"))
TIMEOUT_SEC = int(os.getenv("COMMAND_TIMEOUT_SEC", "30"))


@dataclass
class RunResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_sec: float
    session_id: str
    cwd: str
    timed_out: bool = False


def _new_session() -> Path:
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    p = SANDBOX_ROOT / sid
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_command(command: str) -> RunResult:
    """Execute a shell command string in a fresh sandbox dir."""
    session = _new_session()
    start = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(session),
            executable="/bin/bash",
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
        return RunResult(
            ok=(proc.returncode == 0),
            exit_code=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            duration_sec=time.time() - start,
            session_id=session.name,
            cwd=str(session),
        )
    except subprocess.TimeoutExpired as e:
        timed_out = True
        return RunResult(
            ok=False,
            exit_code=-1,
            stdout=(e.stdout or b"").decode(errors="replace")
            if isinstance(e.stdout, (bytes, bytearray))
            else (e.stdout or ""),
            stderr=("command timed out after %ds" % TIMEOUT_SEC),
            duration_sec=time.time() - start,
            session_id=session.name,
            cwd=str(session),
            timed_out=timed_out,
        )
    finally:
        # Best-effort cleanup; never fatal. `ignore_errors=True` already
        # suppresses most failures, so the only thing left to catch is
        # a permission error from `ignore_errors` itself (rare).
        try:
            shutil.rmtree(session, ignore_errors=True)
        except OSError:
            # Logging here would be a circular dep; swallow silently.
            pass
