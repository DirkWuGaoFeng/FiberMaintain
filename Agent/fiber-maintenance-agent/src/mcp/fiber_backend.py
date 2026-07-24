"""MCP 连接器：统一对接后端 API Gateway（REST :8080）。
规范：单次超时 5s / 最大重试 2 次 / 全链路 trace_id / JSONL 审计。
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


class FiberBackendClient:
    def __init__(self) -> None:
        cfg = settings.backend
        self._base = cfg["base_url"].rstrip("/")
        self._timeout = cfg["timeout_seconds"]
        self._retries = cfg["max_retries"]
        self.batch_limit = cfg["batch_limit"]
        self._audit = AuditLogger(f"{settings.app['log_dir']}/mcp.jsonl")
        self._client: httpx.AsyncClient | None = None
        self.offline = False                 # 离线模式标志（由 watchdog 维护）
        self.down_since: float | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base,
                timeout=httpx.Timeout(self._timeout),
                headers={"X-Source": "fiber-agent"},
            )
        return self._client

    # ───────────────────────── 核心请求 ─────────────────────────
    async def request(self, method: str, path: str,
                      params: dict | None = None,
                      json_body: dict | None = None,
                      retryable: bool = True) -> Any:
        trace_id = trace_id_var.get() or new_trace_id()
        attempt, last_err = 0, None
        max_attempt = (self._retries + 1) if retryable else 1
        started = time.perf_counter()

        while attempt < max_attempt:
            attempt += 1
            status, err = None, None
            try:
                client = await self._get_client()
                resp = await client.request(
                    method, path, params=params, json=json_body,
                    headers={"X-Trace-Id": trace_id},
                )
                status = resp.status_code
                if status == 404:
                    raise NotFound(f"资源不存在: {path}", status=404)
                if status >= 500:
                    raise BackendError(f"后端错误 {status}: {path}", status=status)
                resp.raise_for_status()
                self._mark_up()
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                err = f"连接失败: {e.__class__.__name__}"
                last_err = BackendUnavailable(err)
                self._mark_down()
            except NotFound:
                raise
            except BackendError as e:
                last_err = e
                err = str(e)
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
        ok and self._mark_up() or self._mark_down()
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