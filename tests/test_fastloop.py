"""Tests for the Fast-Loop Interceptor."""

from lever_runner.fastloop import FastLoopInterceptor


def test_valid_input_passes():
    fl = FastLoopInterceptor()
    result = fl.check("check disk usage")
    assert result.action == "EXECUTE_IMMEDIATELY"


def test_shell_injection_blocked():
    fl = FastLoopInterceptor()
    result = fl.check("$(rm -rf /)")
    assert result.action == "ROUTE_TO_DEEP_LOOP"
    assert "Dangerous" in result.reason


def test_cached_failure():
    fl = FastLoopInterceptor()
    fl.check("$(rm -rf /)")  # First time — validation failure cached
    result = fl.check("$(rm -rf /)")  # Second time — should hit cache
    assert "Cached failure" in result.reason


def test_rate_limiting():
    fl = FastLoopInterceptor(max_requests_per_window=3)
    for i in range(5):
        result = fl.check(f"command {i}", sandbox_id="test")
    assert result.action == "ROUTE_TO_DEEP_LOOP"
    assert "Rate limited" in result.reason


def test_latency_under_1ms():
    fl = FastLoopInterceptor()
    result = fl.check("check disk usage")
    assert result.latency_us < 1000  # under 1ms
