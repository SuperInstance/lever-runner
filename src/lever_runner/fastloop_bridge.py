"""
Bridge to fastloop-guard Rust UDS daemon.

If the daemon is running at /tmp/fastloop_guard.sock, use it for sub-50µs validation.
If not, fall back to the Python FastLoopInterceptor (still sub-1ms).

This is the Gemini 4-layer architecture:
- Layer 1: pincherOS sandbox
- Layer 2: fastloop-guard (Rust, this bridge) ← YOU ARE HERE
- Layer 3: intent_extractor + position-aware embeddings
- Layer 4: metal-lathe feedback
"""

import socket
import json
import os
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class GuardResult:
    action: str  # "EXECUTE_IMMEDIATELY", "ROUTE_TO_DEEP_LOOP", "SANDBOX_TERMINATED"
    reason: str
    state_hash: str
    latency_us: int
    backend: str  # "rust" or "python"


class FastLoopBridge:
    """Bridge to fastloop-guard with Python fallback."""
    
    SOCKET_PATH = "/tmp/fastloop_guard.sock"
    
    def __init__(self):
        self._rust_available = os.path.exists(self.SOCKET_PATH)
        if self._rust_available:
            # Test connection
            try:
                self._query_rust("json", '{"test": true}', "health_check", "default")
                self._rust_available = True
            except Exception:
                self._rust_available = False
        
        # Python fallback
        from lever_runner.fastloop import FastLoopInterceptor
        self._python_guard = FastLoopInterceptor()
    
    @property
    def backend(self):
        return "rust" if self._rust_available else "python"
    
    def check(self, text: str, context: str = "", sandbox_id: str = "default") -> GuardResult:
        if self._rust_available:
            try:
                return self._check_rust(text, context, sandbox_id)
            except Exception:
                self._rust_available = False
        
        return self._check_python(text, context, sandbox_id)
    
    def _check_rust(self, text: str, context: str, sandbox_id: str) -> GuardResult:
        start = time.perf_counter()
        
        # Determine type
        text_stripped = text.strip()
        if text_stripped.startswith('{'):
            payload_type = "json"
        elif text_stripped.startswith('def ') or text_stripped.startswith('fn '):
            payload_type = "python"
        else:
            payload_type = "json"  # Default to JSON validation for natural language
        
        result = self._query_rust(payload_type, text, context, sandbox_id)
        latency = int((time.perf_counter() - start) * 1_000_000)
        
        return GuardResult(
            action=result.get("action", "ROUTE_TO_DEEP_LOOP"),
            reason=result.get("reason", "Unknown"),
            state_hash=result.get("state_hash", ""),
            latency_us=latency,
            backend="rust",
        )
    
    def _query_rust(self, payload_type: str, payload: str, context: str, sandbox_id: str) -> dict:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(0.1)  # 100ms timeout
        try:
            sock.connect(self.SOCKET_PATH)
            request = {
                "type": payload_type,
                "payload": payload,
                "context": context,
                "sandbox_id": sandbox_id,
            }
            sock.sendall(json.dumps(request).encode('utf-8'))
            response = sock.recv(4096)
            return json.loads(response.decode('utf-8'))
        finally:
            sock.close()
    
    def _check_python(self, text: str, context: str, sandbox_id: str) -> GuardResult:
        result = self._python_guard.check(text, context, sandbox_id)
        return GuardResult(
            action=result.action,
            reason=result.reason,
            state_hash=result.state_hash,
            latency_us=result.latency_us,
            backend="python",
        )
