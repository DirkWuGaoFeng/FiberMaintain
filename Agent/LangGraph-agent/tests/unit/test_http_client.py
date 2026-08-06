"""HTTP 客户端单元测试 [v7.1]"""

import pytest
from src.tools._http_client import (
    FiberHttpClient,
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
    make_error_json,
    assert_positive_int,
    assert_valid_color,
)


class TestCircuitBreaker:
    """熔断器测试"""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=30)
        for _ in range(3):
            await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_check_raises_when_open(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=30)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await cb.check()

    @pytest.mark.asyncio
    async def test_closes_on_success_in_half_open(self):
        import asyncio
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.15)
        # After cooldown, check() transitions to HALF_OPEN
        await cb.check()
        assert cb.state == CircuitState.HALF_OPEN
        # Success in HALF_OPEN closes the circuit
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestFiberHttpClient:
    """HTTP 客户端测试"""

    def test_client_creation(self):
        client = FiberHttpClient(base_url="http://localhost:8080")
        assert client.base_url == "http://localhost:8080"

    def test_default_max_retries(self):
        client = FiberHttpClient()
        assert client.max_retries == 3

    def test_circuit_breaker_attached(self):
        client = FiberHttpClient()
        assert client.circuit_breaker is not None
        assert client.circuit_breaker.state == CircuitState.CLOSED


class TestBackpressureController:
    """背压控制器测试"""

    def test_initial_error_rate_zero(self):
        from src.tools._http_client import BackpressureController
        bp = BackpressureController()
        assert bp.error_rate == 0.0

    def test_initial_delay_is_base(self):
        from src.tools._http_client import BackpressureController
        bp = BackpressureController(base_delay=0.05)
        assert bp.current_delay == 0.05

    @pytest.mark.asyncio
    async def test_error_rate_calculation(self):
        from src.tools._http_client import BackpressureController
        bp = BackpressureController()
        # Record 8 successes and 2 failures
        for _ in range(8):
            await bp.record(True)
        for _ in range(2):
            await bp.record(False)
        assert abs(bp.error_rate - 0.2) < 0.01

    @pytest.mark.asyncio
    async def test_high_error_rate_increases_delay(self):
        from src.tools._http_client import BackpressureController
        bp = BackpressureController(
            base_delay=0.05,
            error_rate_threshold=0.1,
            max_delay=2.0,
        )
        # Record many failures to push error rate high
        for _ in range(15):
            await bp.record(False)
        for _ in range(5):
            await bp.record(True)
        # Error rate = 15/20 = 0.75, well above threshold
        assert bp.current_delay > 0.05

    @pytest.mark.asyncio
    async def test_window_size_limit(self):
        from src.tools._http_client import BackpressureController
        bp = BackpressureController()
        # Record more than window size (20)
        for _ in range(30):
            await bp.record(True)
        # Window should only keep last 20
        assert len(bp._recent_requests) == 20

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        from src.tools._http_client import BackpressureController
        bp = BackpressureController(base_concurrency=2, base_delay=0.0)
        await bp.acquire()
        bp.release()
        # Should not deadlock


class TestCircuitBreakerAdvanced:
    """熔断器高级场景测试"""

    @pytest.mark.asyncio
    async def test_half_open_probe_failure_reopens(self):
        """Probe failure in HALF_OPEN should re-open circuit."""
        import asyncio
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.15)
        await cb.check()  # Transitions to HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        # Probe fails
        await cb.record_failure()
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_success_decrements_failure_count(self):
        """Success in CLOSED state decrements failure count."""
        cb = CircuitBreaker(failure_threshold=5)
        await cb.record_failure()
        await cb.record_failure()
        assert cb.failure_count == 2
        await cb.record_success()
        assert cb.failure_count == 1

    @pytest.mark.asyncio
    async def test_failure_count_does_not_go_negative(self):
        """Failure count should not go below 0."""
        cb = CircuitBreaker(failure_threshold=5)
        await cb.record_success()
        assert cb.failure_count == 0


class TestFiberHttpClientRetry:
    """HTTP 客户端重试逻辑测试"""

    @pytest.mark.asyncio
    async def test_4xx_no_retry(self):
        """4xx responses should NOT be retried (client error)."""
        import httpx
        from unittest.mock import AsyncMock, patch

        client = FiberHttpClient(base_url="http://mock:8080", max_retries=3)
        call_count = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = httpx.Response(404, request=httpx.Request("GET", "http://mock:8080/test"))
            return resp

        mock_client = AsyncMock()
        mock_client.request = mock_request
        mock_client.is_closed = False
        client.client = mock_client

        result = await client.get("/test")
        # Should only be called once (no retry for 4xx)
        assert call_count == 1


class TestHelpers:
    """辅助函数测试"""

    def test_make_error_json(self):
        import json
        result = json.loads(make_error_json("TEST_ERR", "something failed", "try again"))
        assert result["error"] is True
        assert result["error_code"] == "TEST_ERR"
        assert result["message"] == "something failed"
        assert result["hint"] == "try again"

    def test_make_error_json_unicode(self):
        import json
        result = json.loads(make_error_json("FIBER_ERR", "光纤未找到", "请检查ID"))
        assert result["message"] == "光纤未找到"

    def test_assert_positive_int_valid(self):
        assert_positive_int(1, "test")
        assert_positive_int(100, "test")

    def test_assert_positive_int_invalid(self):
        with pytest.raises(AssertionError):
            assert_positive_int(0, "test")
        with pytest.raises(AssertionError):
            assert_positive_int(-1, "test")

    def test_assert_positive_int_non_int(self):
        with pytest.raises(AssertionError):
            assert_positive_int("1", "test")

    def test_assert_valid_color(self):
        assert_valid_color("RED")
        assert_valid_color("YELLOW")
        assert_valid_color("GREEN")

    def test_assert_valid_color_invalid(self):
        with pytest.raises(AssertionError):
            assert_valid_color("BLUE")
        with pytest.raises(AssertionError):
            assert_valid_color("")
        with pytest.raises(AssertionError):
            assert_valid_color("red")  # Case-sensitive
