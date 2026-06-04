"""Test the Rust→Python fastloop bridge."""


def test_python_fallback():
    """When Rust daemon is not running, Python fallback works."""
    from lever_runner.fastloop_bridge import FastLoopBridge

    bridge = FastLoopBridge()
    result = bridge.check("check disk usage")
    assert result.action == "EXECUTE_IMMEDIATELY"
    assert result.backend == "python"  # Rust daemon likely not running in tests


def test_shell_injection_blocked():
    """Bridge blocks shell injection regardless of backend."""
    from lever_runner.fastloop_bridge import FastLoopBridge

    bridge = FastLoopBridge()
    result = bridge.check("$(rm -rf /)")
    assert result.action == "ROUTE_TO_DEEP_LOOP"


def test_rate_limiting():
    """Bridge respects rate limits."""
    from lever_runner.fastloop_bridge import FastLoopBridge

    bridge = FastLoopBridge()
    for i in range(20):
        result = bridge.check(f"command {i}", sandbox_id="rate_test")
    assert result.action == "ROUTE_TO_DEEP_LOOP"
    assert "Rate" in result.reason
