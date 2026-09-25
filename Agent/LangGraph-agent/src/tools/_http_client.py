"""
共享异步 HTTP 客户端 —— 带熔断器、指数退避重试、背压控制。

【功能说明】
这是所有工具调用 C++ 后端 API Gateway 的唯一数据访问层。
实现 P1（Agent 不做计算）和 P2（单一数据出口）原则。

【核心组件】
1. CircuitBreaker（熔断器）：三态状态机（CLOSED/OPEN/HALF_OPEN）
   防止后端故障时大量请求堆积
2. BackpressureController（背压控制器）：根据错误率动态调整并发和延迟
3. FiberHttpClient（HTTP 客户端）：封装 GET/POST/DELETE + 重试逻辑

【面试知识点】
  Q: 什么是熔断器模式？
  A: 类似电路保险丝。当连续失败次数超过阈值，熔断器“跳闸”（OPEN），
     后续请求直接拒绝，避免压垂后端。冷却期后进入 HALF_OPEN 状态，
     允许一个探测请求，成功则恢复（CLOSED），失败则重新跳闸。
  Q: 什么是背压控制？
  A: 当错误率上升时，自动降低请求速率（增加请求间隔），
     类似交通拥堵时红绿灯时间变长。防止后端过载。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# =============================================================================
# 异常定义
# =============================================================================


class CircuitOpenError(Exception):
    """熔断器开启时抛出，表示请求被拒绝。"""


class BackendUnavailableError(Exception):
    """后端在重试耗尽后完全不可用时抛出。"""


# =============================================================================
# 熔断器（Circuit Breaker）
# 【面试知识点】三态状态机：CLOSED → OPEN → HALF_OPEN → CLOSED
# =============================================================================


class CircuitState(Enum):
    CLOSED = "closed"  # 正常运行，允许请求通过
    OPEN = "open"  # 熔断中，拒绝所有请求
    HALF_OPEN = "half_open"  # 探测中，允许一个请求测试后端是否恢复


class CircuitBreaker:
    """三态熔断器，带冷却计时器。

    【状态转换】
    - CLOSED → OPEN：连续失败次数 ≥ failure_threshold
    - OPEN → HALF_OPEN：冷却时间到期（cooldown_seconds）
    - HALF_OPEN → CLOSED：探测请求成功
    - HALF_OPEN → OPEN：探测请求失败
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 30.0):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    async def check(self) -> None:
        """检查是否允许请求。熔断器 OPEN 时抛出 CircuitOpenError。"""
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return
            if self.state == CircuitState.OPEN:
                # 检查冷却时间是否已到 -> 转入 HALF_OPEN 状态
                if time.monotonic() - (self._opened_at or 0) >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    logger.info("[CircuitBreaker] OPEN -> HALF_OPEN (cooldown elapsed)")
                    return  # 允许一个探测请求
                raise CircuitOpenError(f"Circuit breaker OPEN, cooldown {self.cooldown_seconds}s not elapsed")
            # HALF_OPEN：放行探测请求

    async def record_success(self) -> None:
        """记录成功请求。HALF_OPEN 状态下成功则恢复为 CLOSED。"""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                logger.info("[CircuitBreaker] HALF_OPEN -> CLOSED (probe success)")
            elif self.state == CircuitState.CLOSED:
                self.failure_count = max(0, self.failure_count - 1)

    async def record_failure(self) -> None:
        """记录失败请求。可能触发熔断器跳闸。"""
        async with self._lock:
            self.failure_count += 1
            if self.state == CircuitState.HALF_OPEN:
                # 探测失败，重新跳闸（OPEN）
                self.state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                logger.warning("[CircuitBreaker] HALF_OPEN -> OPEN (probe failed)")
            elif self.state == CircuitState.CLOSED:
                if self.failure_count >= self.failure_threshold:
                    self.state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    logger.warning(f"[CircuitBreaker] CLOSED -> OPEN (failures={self.failure_count})")


# =============================================================================
# 背压控制器（Backpressure Controller）
# 【设计说明】根据滑动窗口的错误率动态调整请求间隔
# =============================================================================


class BackpressureController:
    """基于错误率的动态并发控制。

    【工作原理】
    维护一个滑动窗口（默认 20 条）记录最近请求的成功/失败。
    当错误率超过阈值时，线性增加请求间隔延迟，最高到 max_delay。
    """

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

        self._recent_requests: list[bool] = []  # True=成功，False=失败
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
        """根据错误率计算请求间隔延迟。"""
        rate = self.error_rate
        if rate <= self.error_rate_threshold:
            return self.base_delay
        # 线性增加：错误率达 50% 时达到 max_delay
        factor = min(1.0, (rate - self.error_rate_threshold) / 0.4)
        return self.base_delay + factor * (self.max_delay - self.base_delay)

    async def record(self, success: bool) -> None:
        async with self._lock:
            self._recent_requests.append(success)
            if len(self._recent_requests) > self._window_size:
                self._recent_requests.pop(0)

    async def acquire(self) -> None:
        """等待信号量 + 背压延迟。"""
        await self._semaphore.acquire()
        delay = self.current_delay
        if delay > 0:
            await asyncio.sleep(delay)

    def release(self) -> None:
        self._semaphore.release()


# =============================================================================
# FiberHttpClient - 主客户端
# 【设计说明】所有工具的统一 HTTP 出口，集成熔断器 + 重试 + 背压
# =============================================================================


class FiberHttpClient:
    """异步 HTTP 客户端，集成熔断器、重试、背压控制。

    【超时分级】
    - 单条查询：2s
    - 完整查询：3s
    - 批量操作：5s
    - 导出操作：10s

    【面试知识点】
    - 为什么分级超时？不同类型的操作合理等待时间不同，
      单条查询应快速返回，批量操作可以等更久。
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
                timeout=httpx.Timeout(10.0),  # 最大超时；单次请求可在下方覆盖
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self.client

    async def close(self) -> None:
        if self.client and not self.client.is_closed:
            await self.client.aclose()

    # -- 公共 API --

    async def get(self, path: str, timeout: float = 2.0, params: Optional[dict] = None) -> str:
        """GET 请求，带熔断器 + 重试 + 背压。"""
        return await self._request("GET", path, timeout=timeout, params=params)

    async def post(self, path: str, json: dict | None = None, timeout: float = 5.0) -> str:
        """POST 请求，带熔断器 + 重试 + 背压。"""
        return await self._request("POST", path, timeout=timeout, json=json)

    async def delete(self, path: str, timeout: float = 3.0, params: Optional[dict] = None) -> str:
        """DELETE 请求，带熔断器 + 重试 + 背压。"""
        return await self._request("DELETE", path, timeout=timeout, params=params)

    # -- 内部实现 --

    async def _request(
        self,
        method: str,
        path: str,
        timeout: float = 2.0,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> str:
        """执行请求，完整弹性管线：熔断检查 → 背压节流 → 重试循环。"""
        # 获取 trace_id 用于日志跟踪
        from ..observability.request_tracer import get_current_trace_id

        trace_id = get_current_trace_id()

        # 1. 熔断器检查
        await self.circuit_breaker.check()

        # 2. 背压节流
        await self.backpressure.acquire()

        client = await self._ensure_client()
        last_error: Optional[Exception] = None
        request_start = time.time()

        logger.info(
            f"[HTTP-TRACE:{trace_id}] {method} {path} timeout={timeout}s " f"params={params}"
            if params
            else f"[HTTP-TRACE:{trace_id}] {method} {path} timeout={timeout}s"
        )

        try:
            for attempt in range(self.max_retries):
                attempt_start = time.time()
                try:
                    # 注入 X-Trace-Id 头，实现跨服务跟踪透传
                    headers = {"X-Trace-Id": trace_id} if trace_id else {}
                    resp = await client.request(
                        method,
                        path,
                        timeout=httpx.Timeout(timeout),
                        params=params,
                        json=json,
                        headers=headers,
                    )

                    elapsed_ms = round((time.time() - attempt_start) * 1000, 2)
                    body_preview = resp.text[:100] + "..." if len(resp.text) > 100 else resp.text

                    # 4xx：不重试（客户端错误）
                    if 400 <= resp.status_code < 500:
                        logger.info(
                            f"[HTTP-TRACE:{trace_id}] {method} {path} "
                            f"status={resp.status_code} elapsed={elapsed_ms}ms (client error, no retry)"
                        )
                        await self.backpressure.record(True)
                        await self.circuit_breaker.record_success()
                        return resp.text

                    # 5xx：指数退避重试
                    if resp.status_code >= 500:
                        logger.warning(
                            f"[HTTP-TRACE:{trace_id}] {method} {path} "
                            f"status={resp.status_code} elapsed={elapsed_ms}ms (server error)"
                        )
                        raise httpx.HTTPStatusError(
                            f"Server error {resp.status_code}",
                            request=resp.request,
                            response=resp,
                        )

                    # 2xx/3xx：成功
                    logger.info(
                        f"[HTTP-TRACE:{trace_id}] {method} {path} "
                        f"status={resp.status_code} elapsed={elapsed_ms}ms body={body_preview}"
                    )
                    await self.backpressure.record(True)
                    await self.circuit_breaker.record_success()
                    return resp.text

                except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError) as e:
                    last_error = e
                    elapsed_ms = round((time.time() - attempt_start) * 1000, 2)
                    await self.backpressure.record(False)
                    await self.circuit_breaker.record_failure()

                    if attempt < self.max_retries - 1:
                        backoff = 0.5 * (attempt + 1)
                        logger.warning(
                            f"[HTTP-TRACE:{trace_id}] {method} {path} "
                            f"attempt={attempt+1}/{self.max_retries} failed={type(e).__name__} "
                            f"elapsed={elapsed_ms}ms retry_in={backoff}s"
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            f"[HTTP-TRACE:{trace_id}] {method} {path} "
                            f"all {self.max_retries} attempts failed, last_error={e}"
                        )

            total_ms = round((time.time() - request_start) * 1000, 2)
            raise BackendUnavailableError(
                f"Backend unavailable after {self.max_retries} retries ({total_ms}ms): {last_error}"
            )
        finally:
            self.backpressure.release()

    # -- 健康检查 --

    async def health_check(self) -> bool:
        """检查后端是否可达。"""
        try:
            result = await self.get("/health", timeout=2.0)
            return '"ok"' in result or '"status"' in result
        except Exception:
            return False


# =============================================================================
# 结构化错误辅助 [v7.1 Layer 3]
# =============================================================================


def make_error_json(error_code: str, message: str, hint: str = "") -> str:
    """构建工具响应的结构化错误 JSON。"""
    import json as _json

    return _json.dumps(
        {
            "error": True,
            "error_code": error_code,
            "message": message,
            "hint": hint,
        },
        ensure_ascii=False,
    )


def assert_positive_int(value: int, name: str) -> None:
    """Layer 3 断言：值必须是正整数。"""
    assert isinstance(value, int) and value > 0, f"[Layer3] {name} must be positive int, got {value!r}"


def assert_valid_color(color: str) -> None:
    """Layer 3 断言：颜色必须是 RED/YELLOW/GREEN。"""
    assert color in ("RED", "YELLOW", "GREEN"), f"[Layer3] Invalid color '{color}', must be RED/YELLOW/GREEN"


# =============================================================================
# 模块级单例
# 【设计说明】所有工具共享同一个 HTTP 客户端实例，复用连接池
# =============================================================================

fiber_http_client = FiberHttpClient()
