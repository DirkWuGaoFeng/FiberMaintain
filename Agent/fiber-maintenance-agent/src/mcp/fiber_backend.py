"""MCP 连接器 v3.2.1：统一对接后端 API Gateway（REST :8080）。
规范：分级超时(单查2s/批量5s/趋势3s/RAG3s) / 熔断器(5次/分钟) / 全链路 trace_id / JSONL 审计。
"""
from __future__ import annotations
import asyncio, json, time, uuid, logging
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from src.settings import settings
from src.monitoring.metrics import MCP_CALLS, MCP_ERRORS, MCP_LATENCY

logger = logging.getLogger("fiber.mcp")

# 全链路 trace_id（与后端 C++ 日志关联）
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")

INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1


class BackendError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status

class BackendUnavailable(BackendError):
    """连接失败/超时（不重试场景由调用方决定）。"""

class NotFound(BackendError):
    pass


class AuditLogger:
    """JSON Lines 审计日志。"""
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._path = path

    def write(self, record: dict) -> None:
        record.setdefault("timestamp",
                          datetime.now(timezone.utc).astimezone().isoformat())
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def new_trace_id() -> str:
    tid = uuid.uuid4().hex[:16]
    trace_id_var.set(tid)
    return tid


class CircuitBreaker:
    """熔断器：5次/分钟阈值, 30s冷却, 半开探测。"""
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断中
    HALF_OPEN = "half_open" # 探测中

    def __init__(self, threshold: int = 5, cooldown: float = 30.0):
        self._threshold = threshold
        self._cooldown = cooldown
        self._state = self.CLOSED
        self._errors: list[float] = []
        self._opened_at: float | None = None

    @property
    def state(self) -> str:
        if self._state == self.OPEN:
            if time.time() - (self._opened_at or 0) > self._cooldown:
                self._state = self.HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        s = self.state
        if s == self.CLOSED:
            return True
        if s == self.HALF_OPEN:
            return True  # 允许探测请求
        return False  # OPEN

    def record_success(self) -> None:
        if self._state == self.HALF_OPEN:
            self._state = self.CLOSED
            self._errors.clear()
            logger.info("CircuitBreaker: 半开探测成功，恢复关闭")

    def record_failure(self) -> None:
        now = time.time()
        self._errors = [t for t in self._errors if now - t < 60]
        self._errors.append(now)

        if self._state == self.HALF_OPEN:
            self._state = self.OPEN
            self._opened_at = now
            logger.warning("CircuitBreaker: 半开探测失败，重新熔断")
        elif len(self._errors) >= self._threshold:
            self._state = self.OPEN
            self._opened_at = now
            logger.warning("CircuitBreaker: %d次/分钟，熔断%ss",
                           len(self._errors), self._cooldown)


# 分级超时配置
TIERED_TIMEOUTS = {
    "single": 2.0,    # 单查
    "batch": 5.0,     # 批量
    "trend": 3.0,     # 趋势
    "rag": 3.0,       # RAG
    "default": 3.0,
}


def _classify_timeout(path: str) -> float:
    """根据路径分类确定超时时间。"""
    if "batch" in path or "bulk" in path:
        return TIERED_TIMEOUTS["batch"]
    if "trend" in path or "stats" in path:
        return TIERED_TIMEOUTS["trend"]
    if "rag" in path or "knowledge" in path or "search" in path:
        return TIERED_TIMEOUTS["rag"]
    if "/fibers/" in path and path.rstrip("/").split("/")[-1].isdigit():
        return TIERED_TIMEOUTS["single"]
    return TIERED_TIMEOUTS["default"]


class FiberBackendClient:
    def __init__(self) -> None:
        cfg = settings.backend
        self._base = cfg["base_url"].rstrip("/")
        self._timeout = cfg["timeout_seconds"]
        self._retries = cfg["max_retries"]
        self.batch_limit = cfg.get("batch_limit", 200)
        self._audit = AuditLogger(f"{settings.app['log_dir']}/mcp.jsonl")
        self._client: httpx.AsyncClient | None = None
        self.offline = False
        self.down_since: float | None = None
        self._circuit = CircuitBreaker()

    async def _get_client(self, timeout: float | None = None) -> httpx.AsyncClient:
        t = timeout or self._timeout
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base,
                timeout=httpx.Timeout(t),
                headers={"X-Source": "fiber-agent"},
            )
        elif t != self._timeout:
            # 分级超时：重新设置超时
            self._client.timeout = httpx.Timeout(t)
        return self._client

    # ───────────────────────── 核心请求 ─────────────────────────
    async def request(self, method: str, path: str,
                      params: dict | None = None,
                      json_body: dict | None = None,
                      retryable: bool = True) -> Any:
        # 熔断器检查
        if not self._circuit.allow_request():
            raise BackendUnavailable(
                f"熔断器开启中，拒绝请求: {path}")

        trace_id = trace_id_var.get() or new_trace_id()
        tiered_timeout = _classify_timeout(path)
        attempt, last_err = 0, None
        max_attempt = (self._retries + 1) if retryable else 1
        started = time.perf_counter()

        while attempt < max_attempt:
            attempt += 1
            status, err = None, None
            try:
                client = await self._get_client(timeout=tiered_timeout)
                resp = await client.request(
                    method, path, params=params, json=json_body,
                    headers={"X-Trace-Id": trace_id},
                )
                status = resp.status_code

                # 重试决策树：4xx不重试, 5xx退避, 超时重试1次
                if status == 404:
                    self._circuit.record_success()
                    raise NotFound(f"资源不存在: {path}", status=404)
                if 400 <= status < 500:
                    # 4xx 客户端错误：不重试
                    self._circuit.record_success()
                    raise BackendError(f"客户端错误 {status}", status=status)
                if status >= 500:
                    raise BackendError(f"后端错误 {status}: {path}", status=status)

                resp.raise_for_status()
                self._mark_up()
                self._circuit.record_success()
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                err = f"连接失败: {e.__class__.__name__}"
                last_err = BackendUnavailable(err)
                self._mark_down()
                self._circuit.record_failure()
                # 超时仅重试1次
                if isinstance(e, httpx.TimeoutException) and attempt > 1:
                    break
            except NotFound:
                raise
            except BackendError as e:
                last_err = e
                err = str(e)
                if e.status and e.status >= 500:
                    self._circuit.record_failure()
            except httpx.HTTPError as e:
                last_err = BackendError(str(e))
                err = str(e)
            finally:
                elapsed = (time.perf_counter() - started) * 1000
                MCP_CALLS.labels(method=method, path=path,
                                 status=status or "ERR").inc()
                MCP_LATENCY.labels(path=path).observe(elapsed / 1000)
                if err:
                    MCP_ERRORS.labels(path=path).inc()
                self._audit.write({
                    "event": "mcp_call", "trace_id": trace_id,
                    "method": method, "path": path,
                    "params": params, "attempt": attempt,
                    "status": status or "ERR", "error": err,
                    "elapsed_ms": round(elapsed, 2),
                    "circuit": self._circuit.state,
                    "timeout_tier": tiered_timeout,
                })
            # 指数退避：0.3s → 0.6s
            if attempt < max_attempt:
                await asyncio.sleep(0.3 * (2 ** (attempt - 1)))

        raise last_err or BackendUnavailable("后端不可用")

    # ───────────────────────── 健康探测 ─────────────────────────
    async def health(self) -> bool:
        try:
            client = await self._get_client()
            r = await client.get(settings.backend["health_path"],
                                 timeout=3.0)
            ok = r.status_code == 200
        except httpx.HTTPError:
            ok = False
        if ok:
            self._mark_up()
        else:
            self._mark_down()
        return ok

    def _mark_up(self) -> None:
        self.offline, self.down_since = False, None

    def _mark_down(self) -> None:
        if not self.offline:
            self.offline, self.down_since = True, time.time()

    # ───────────────────────── 业务 API ─────────────────────────
    @staticmethod
    def _check_fid(fiber_id: int) -> None:
        if not (INT32_MIN <= fiber_id <= INT32_MAX):
            raise ValueError(f"fiber_id 超出 int32 范围: {fiber_id}")

    async def get_fiber(self, fiber_id: int) -> dict:
        self._check_fid(fiber_id)
        return await self.request("GET", f"/api/v1/topology/fibers/{fiber_id}")

    async def get_fiber_scene(self, fiber_id: int) -> dict:
        self._check_fid(fiber_id)
        return await self.request("GET", f"/api/v1/topology/fibers/{fiber_id}/scene")

    async def batch_fibers(self, fiber_ids: list[int]) -> dict:
        if len(fiber_ids) > self.batch_limit:
            raise ValueError(f"批量查询上限 {self.batch_limit} 条")
        for fid in fiber_ids:
            self._check_fid(fid)
        return await self.request("POST", "/api/v1/topology/fibers/batch",
                                  json_body={"fiber_ids": fiber_ids})

    async def get_board(self, board_id: int) -> dict:
        return await self.request("GET", f"/api/v1/boards/{board_id}")

    async def batch_boards(self, board_ids: list[int]) -> dict:
        return await self.request("POST", "/api/v1/boards/batch",
                                  json_body={"board_ids": board_ids})

    async def get_performance(self, fiber_id: int) -> dict:
        self._check_fid(fiber_id)
        return await self.request("GET", f"/api/v1/fibers/{fiber_id}/performance")

    async def get_spanloss(self, fiber_id: int) -> dict:
        self._check_fid(fiber_id)
        return await self.request("GET", f"/api/v1/fibers/{fiber_id}/spanloss")

    async def get_alarms(self, board_id: int | None = None,
                         port_id: int | None = None) -> dict:
        params = {}
        if board_id is not None: params["board_id"] = board_id
        if port_id is not None: params["port_id"] = port_id
        return await self.request("GET", "/api/v1/alarms/current", params=params)

    async def get_colored(self, color: str) -> dict:
        if color not in ("RED", "YELLOW"):
            raise ValueError("color 仅支持 RED | YELLOW")
        return await self.request("GET", "/api/v1/fibers/colored",
                                  params={"color": color})

    async def get_all_colored(self) -> dict:
        return await self.request("GET", "/api/v1/fibers/colored/all")

    async def get_stats_realtime(self) -> dict:
        return await self.request("GET", "/api/v1/fibers/stats/realtime")

    async def get_stats_trend(self, start_time: str, end_time: str) -> dict:
        return await self.request("GET", "/api/v1/fibers/stats/trend",
                                  params={"start_time": start_time,
                                          "end_time": end_time})

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


backend = FiberBackendClient()