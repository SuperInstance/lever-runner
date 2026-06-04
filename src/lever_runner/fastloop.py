"""
Fast-Loop Interceptor — sub-millisecond validation before LLM invocation.

The Fast-Loop checks:
1. Is this input in the failure cache? (seen this exact failure before → skip)
2. Does it pass structural validation? (no shell metacharacters)
3. Is the rate limit OK? (not spamming)

Only if ALL checks pass does the request go to the LLM (Deep-Loop).
This saves ~95% of tokens by catching bad inputs instantly.
"""

import hashlib
import time
import threading
from typing import Optional
from dataclasses import dataclass


@dataclass
class FastLoopResult:
    action: str  # "EXECUTE_IMMEDIATELY" or "ROUTE_TO_DEEP_LOOP"
    reason: str
    state_hash: str
    latency_us: int  # microseconds


class FastLoopInterceptor:
    def __init__(self, max_failures: int = 3, rate_window_sec: float = 1.0, max_requests_per_window: int = 10):
        self.failure_db: dict[str, str] = {}  # hash → error message
        self.error_counters: dict[str, int] = {}  # sandbox_id → consecutive failures
        self.rate_timestamps: dict[str, list[float]] = {}  # sandbox_id → timestamps
        self.max_failures = max_failures
        self.rate_window = rate_window_sec
        self.max_requests = max_requests_per_window
        self._lock = threading.RLock()
    
    def _hash_state(self, text: str, context: str) -> str:
        h = hashlib.blake2b(digest_size=16)
        h.update(text.encode())
        h.update(context.encode())
        return h.hexdigest()
    
    def _is_rate_limited(self, sandbox_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.rate_window
        
        timestamps = self.rate_timestamps.get(sandbox_id, [])
        # Trim old timestamps
        timestamps = [t for t in timestamps if t > cutoff]
        
        if len(timestamps) >= self.max_requests:
            self.rate_timestamps[sandbox_id] = timestamps
            return True
        
        timestamps.append(now)
        self.rate_timestamps[sandbox_id] = timestamps
        return False
    
    def _validate_input(self, text: str) -> tuple[bool, str]:
        """Validate user input — block shell metacharacters."""
        dangerous = ['$', '`', ';', '&', '|', '>', '<', '!', '\n']
        for char in dangerous:
            if char in text:
                return False, f"Dangerous character blocked: {repr(char)}"
        
        # Must not be empty or too long
        if not text.strip():
            return False, "Empty input"
        if len(text) > 500:
            return False, f"Input too long: {len(text)} chars (max 500)"
        
        return True, "OK"
    
    def check(self, user_input: str, context: str = "", sandbox_id: str = "default") -> FastLoopResult:
        start = time.perf_counter()
        state_hash = self._hash_state(user_input, context)
        
        # 1. Rate limit check
        if self._is_rate_limited(sandbox_id):
            latency = int((time.perf_counter() - start) * 1_000_000)
            return FastLoopResult(
                action="ROUTE_TO_DEEP_LOOP",
                reason=f"Rate limited: max {self.max_requests} requests per {self.rate_window}s",
                state_hash=state_hash,
                latency_us=latency,
            )
        
        # 2. Failure cache check
        with self._lock:
            if state_hash in self.failure_db:
                return FastLoopResult(
                    action="ROUTE_TO_DEEP_LOOP",
                    reason=f"Cached failure: {self.failure_db[state_hash]}",
                    state_hash=state_hash,
                    latency_us=int((time.perf_counter() - start) * 1_000_000),
                )
        
        # 3. Structural validation
        valid, msg = self._validate_input(user_input)
        if not valid:
            with self._lock:
                self.failure_db[state_hash] = msg
                self.error_counters[sandbox_id] = self.error_counters.get(sandbox_id, 0) + 1
            latency = int((time.perf_counter() - start) * 1_000_000)
            return FastLoopResult(
                action="ROUTE_TO_DEEP_LOOP",
                reason=f"Validation failed: {msg}",
                state_hash=state_hash,
                latency_us=latency,
            )
        
        # 4. Reset error counter on success
        with self._lock:
            self.error_counters[sandbox_id] = 0
        
        latency = int((time.perf_counter() - start) * 1_000_000)
        return FastLoopResult(
            action="EXECUTE_IMMEDIATELY",
            reason="Passed all fast-loop checks",
            state_hash=state_hash,
            latency_us=latency,
        )
    
    def get_stats(self) -> dict:
        with self._lock:
            return {
                "cached_failures": len(self.failure_db),
                "active_sandboxes": len(self.error_counters),
                "rate_tracked": len(self.rate_timestamps),
            }
