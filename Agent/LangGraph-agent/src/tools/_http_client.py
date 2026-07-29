"""
Shared async HTTP client with circuit breaker, exponential backoff retry, and backpressure control.

This is the single data access layer for all Tools that call the C++ backend API Gateway.
Implements P1 (Agent does no computation) and P2 (single data exit point) principles.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from enum import Enum
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================

class CircuitOpenError(Exception):
    """Raised when the circuit breaker is open and requests are rejected."""
    pass


class BackendUnavailableError(Exception):
    """Raised when the backend is completely unavailable after retries."""
    pass


# =============================================================================
# Circuit Breaker
# =============================================================================

class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Tripped, rejecting requests
    HALF_OPEN = "half_open"  # Testing if backend recovered


class CircuitBreaker:
    """Three-state circuit breaker with cooldown timer."""

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    async def check(self) -> None:
        """Check if request is allowed. Raises CircuitOpenError if open."""
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return
            if self.state == CircuitState.OPEN:
                # Check if cooldown has elapsed -> transition to HALF_OPEN
                if time.monotonic() - (self._opened_at or 0) >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("[CircuitBreaker] OPEN -> HALF_OPEN (cooldown elapsed)")
                    return  # Allow one probe request
                raise CircuitOpenError(
                    f"Circuit breaker OPEN, cooldown {self.cooldown_seconds}s not elapsed"
                )
            # HALF_OPEN: allow the probe request through

    async def record_success(self) -> None:
        """Record a successful request."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info("[CircuitBreaker] HALF_OPEN -> CLOSED (probe success)")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)

    async def record_failure(self) -> None:
        """Record a failed request. May trip the breaker."""
        async with self._lock:
            self.failure_count += 1
            if self.state == CircuitState.HALF_OPEN:
                # Probe failed, re-open
                self.state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning("[CircuitBreaker] HALF_OPEN -> OPEN (probe failed)")
            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    logger.warning(
                        f"[CircuitBreaker] CLOSED -> OPEN (failures={self.failure_count})"
                    )


# =============================================================================
# Backpressure Controller
# =============================================================================

class BackpressureController:
    """Dynamic concurrency control based on error rate."""

    def __init__(
        self,
        base_concurrency: int = 5,
        base_delay: float = 0.05,
        error_rate_threshold: float = 0.1,
        max_delay: float = 2.0,
    ):
        self.base_concurrency = base_concurrency
        self.base_delay = base_delay
        self.error_rate_threshold = error_rate_threshold
        self.max_delay = max_delay

        self._recent_requests: list[bool] = []  # True=success, False=failure
        self._window_size = 20
        self._semaphore = asyncio.Semaphore(base_concurrency)
        self._lock = asyncio.Lock()

    @property
    def error_rate(self) -> float:
        if not self._recent_requests:
            return 0.0
        failures = sum(1 for r in self._recent_requests if not r)
        return failures / len(self._recent_requests)

    @property
    def current_delay(self) -> float:
        """Calculate inter-request delay based on error rate."""
        rate = self.error_rate
        if rate <= self.error_rate_threshold:
            return self.base_delay
        # Linear increase: at 50% error rate -> max_delay
        factor = min(1.0, (rate - self.error_rate_threshold) / 0.4)
        return self.base_delay + factor * (self.max_delay - self.base_delay)

    async def record(self, success: bool) -> None:
        async with self._lock:
            self._recent_requests.append(success)
            if len(self._recent_requests) > self._window_size:
                self._recent_requests.pop(0)

    async def acquire(self) -> None:
        """Wait for semaphore + backpressure delay."""
        await self._semaphore.acquire()
        delay = self.current_delay
        if delay > 0:
            await asyncio.sleep(delay)

    def release(self) -> None:
        self._semaphore.release()


# =============================================================================
# FiberHttpClient - Main Client
# =============================================================================

class FiberHttpClient:
    """
    Async HTTP client with circuit breaker, retry, and backpressure.

    Timeout tiers:
      - Single query: 2s
      - Full query:   3s
      - Batch ops:    5s
      - Export:       10s
    """

    def __init__(
        self,
        base_url: str = "",
        max_retries: int = 3,
        circuit_breaker: Optional[CircuitBreaker] = None,
        backpressure: Optional[BackpressureController] = None,
    ):
        self.base_url = base_url or os.environ.get("FIBER_BACKEND_URL", "http://localhost:8080")
        self.max_retries = max_retries
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=int(os.environ.get("CIRCUIT_BREAKER_THRESHOLD", "5")),
            cooldown_seconds=float(os.environ.get("CIRCUIT_BREAKER_COOLDOWN", "30")),
        )
        self.backpressure = backpressure or BackpressureController()
        self.client: Optional[httpx.AsyncClient] = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self.client is None or self.client.is_closed:
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(10.0),  # Max timeout; per-request overrides below
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self.client

    async def close(self) -> None:
        if self.client and not self.client.is_closed:
            await self.client.aclose()

    # -- Public API --

    async def get(self, path: str, timeout: float = 2.0, params: Optional[dict] = None) -> str:
        """GET request with circuit breaker + retry + backpressure."""
        return await self._request("GET", path, timeout=timeout, params=params)

    async def post(self, path: str, json: dict | None = None, timeout: float = 5.0) -> str:
        """POST request with circuit breaker + retry + backpressure."""
        return await self._request("POST", path, timeout=timeout, json=json)

    # -- Internal --

    async def _request(
        self,
        method: str,
        path: str,
        timeout: float = 2.0,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> str:
        """Execute request with full resilience pipeline."""
        # 1. Circuit breaker check
        await self.circuit_breaker.check()

        # 2. Backpressure throttle
        await self.backpressure.acquire()

        client = await self._ensure_client()
        last_error: Optional[Exception] = None

        try:
            for attempt in range(self.max_retries):
                try:
                    resp = await client.request(
                        method,
                        path,
                        timeout=httpx.Timeout(timeout),
                        params=params,
                        json=json,
                    )

                    # 4xx: do not retry (client error)
                    if 400 <= resp.status_code < 500:
                        await self.backpressure.record(True)
                        await self.circuit_breaker.record_success()
                        return resp.text

                    # 5xx: retry with backoff
                    if resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"Server error {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )

                    # 2xx/3xx: success
                    await self.backpressure.record(True)
                    await self.circuit_breaker.record_success()
                    return resp.text

                except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
                    last_error = e
                    await self.backpressure.record(False)
                    await self.circuit_breaker.record_failure()

                    if attempt < self.max_retries - 1:
                        backoff = 0.5 * (attempt + 1)
                        logger.warning(
                            f"[HTTPClient] {method} {path} attempt={attempt+1} failed: {e}, "
                            f"retrying in {backoff}s"
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"[HTTPClient] {method} {path} all {self.max_retries} attempts failed"
                        )

            raise BackendUnavailableError(
                f"Backend unavailable after {self.max_retries} retries: {last_error}"
            )
        finally:
            self.backpressure.release()

    # -- Health check --

    async def health_check(self) -> bool:
        """Check if the backend is reachable."""
        try:
            result = await self.get("/health", timeout=2.0)
            return '"ok"' in result
        except Exception:
            return False


# =============================================================================
# Module-level singleton
# =============================================================================

fiber_http_client = FiberHttpClient()
