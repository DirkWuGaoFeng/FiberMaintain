"""HTTP 客户端单元测试"""

import pytest
from src.tools._http_client import FiberHttpClient, CircuitBreaker, CircuitState


class TestCircuitBreaker:
    """熔断器测试"""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30)
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_half_open_after_cooldown(self):
        import time
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_on_success_in_half_open(self):
        import time
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestFiberHttpClient:
    """HTTP 客户端测试"""

    def test_client_creation(self):
        client = FiberHttpClient(base_url="http://localhost:8080")
        assert client.base_url == "http://localhost:8080"

    def test_timeout_tiers(self):
        client = FiberHttpClient(base_url="http://localhost:8080")
        assert client._timeouts["single"] == 2.0
        assert client._timeouts["batch"] == 5.0
        assert client._timeouts["export"] == 10.0
