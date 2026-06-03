"""
helpers.py — shared test utilities for lever-runner tests.

Contains fake data classes matching orchestrator/executor/store shapes
so tests can instantiate them without importing production modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FakeMatch:
    """Mimics store.Match so we can inject into DoResult."""

    id: str = "abc12345"
    intent_phrase: str = "test command"
    command: str = "echo hello"
    trust_score: float = 75.0
    success_count: int = 10
    failure_count: int = 2
    score: float = 0.15
    similarity: float = 0.85


@dataclass
class FakeRunResult:
    """Mimics executor.RunResult."""

    ok: bool = True
    exit_code: int = 0
    stdout: str = "hello world"
    stderr: str = ""
    duration_sec: float = 0.42
    session_id: str = "sess000001"
    cwd: str = "/tmp/lever-runner/sess000001"
    timed_out: bool = False


@dataclass
class FakeDoResult:
    """Mimics orchestrator.DoResult."""

    ok: bool = True
    user_request: str = "test this"
    intent: str = "test command"
    match: FakeMatch | None = field(default_factory=FakeMatch)
    run: FakeRunResult | None = field(default_factory=FakeRunResult)
    tokens_in: int = 50
    tokens_out: int = 10
    error: str | None = None
    no_match: bool = False

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out
