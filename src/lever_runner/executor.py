"""
executor.py — run a pre-approved command in a per-session sandbox.

The LLM never knows this module exists. We chdir into a per-session
scratch dir, run the command with a restricted environment, minimal PATH,
resource limits, and a hard timeout with process-group kill, then capture
stdout/stderr.
"""

from __future__ import annotations

import os
import resource
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

SANDBOX_ROOT = Path(os.getenv("SANDBOX_ROOT", "/tmp/lever-runner"))
TIMEOUT_SEC = int(os.getenv("COMMAND_TIMEOUT_SEC", "30"))

# Resource limits (tunable via env)
MAX_CPU_SEC = int(os.getenv("SANDBOX_RLIMIT_CPU", "30"))
MAX_MEMORY_MB = int(os.getenv("SANDBOX_RLIMIT_AS_MB", "512"))

# Allowed PATH entries — only standard system paths
SANDBOX_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Environment variables whitelisted for sandboxed commands
_ENV_WHITELIST = frozenset({
    "HOME", "USER", "LOGNAME", "TERM", "LANG", "LC_ALL", "LC_CTYPE",
    "TZ", "PATH", "TMPDIR", "HOSTNAME",
    # Allow proxy vars through
    "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
    "no_proxy", "NO_PROXY",
})


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


def _sandbox_env() -> dict[str, str]:
    """Build a minimal environment with only whitelisted variables."""
    env = {}
    for key in _ENV_WHITELIST:
        if key in os.environ:
            env[key] = os.environ[key]
    # Always override PATH with our restricted version
    env["PATH"] = SANDBOX_PATH
    # Point TMPDIR into the session dir for extra isolation
    return env


def _set_resource_limits() -> None:
    """Apply RLIMIT_CPU and RLIMIT_AS to the child process (called via preexec_fn)."""
    # CPU time limit (seconds) — gives ~2x wall-clock as buffer
    if MAX_CPU_SEC > 0:
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SEC, MAX_CPU_SEC))
        except (ValueError, OSError):
            pass
    # Address space limit (bytes)
    if MAX_MEMORY_MB > 0:
        try:
            max_bytes = MAX_MEMORY_MB * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (max_bytes, max_bytes))
        except (ValueError, OSError):
            pass


def run_command(command: str) -> RunResult:
    """Execute a shell command string in a fresh sandbox dir with
    restricted env, resource limits, and process-group kill on timeout."""
    session = _new_session()
    start = time.time()
    timed_out = False
    env = _sandbox_env()
    env["TMPDIR"] = str(session)

    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(session),
            executable="/bin/bash",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            preexec_fn=_set_resource_limits,
            start_new_session=True,  # new process group for clean kill
        )
        try:
            stdout, stderr = proc.communicate(timeout=TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Kill the entire process group
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                proc.kill()
            stdout, stderr = proc.communicate(timeout=5)
            return RunResult(
                ok=False,
                exit_code=-1,
                stdout=stdout or "",
                stderr=("command timed out after %ds" % TIMEOUT_SEC),
                duration_sec=time.time() - start,
                session_id=session.name,
                cwd=str(session),
                timed_out=timed_out,
            )

        return RunResult(
            ok=(proc.returncode == 0),
            exit_code=proc.returncode or 0,
            stdout=stdout,
            stderr=stderr,
            duration_sec=time.time() - start,
            session_id=session.name,
            cwd=str(session),
        )
    except Exception as exc:
        return RunResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            duration_sec=time.time() - start,
            session_id=session.name,
            cwd=str(session),
        )
    finally:
        # Best-effort cleanup; never fatal.
        try:
            shutil.rmtree(session, ignore_errors=True)
        except OSError:
            pass
