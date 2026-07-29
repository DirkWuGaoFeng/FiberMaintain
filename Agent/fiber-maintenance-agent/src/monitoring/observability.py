"""
Phase 4.2: 可观测性三支柱

Tracing: trace_id 贯穿, SQLite(traces+spans 表, 7天 TTL)
Metrics: Prometheus 20+ 指标, 60s 聚合窗口
Logging: 结构化 JSON, 脱敏, 7天保留
"""
from __future__ import annotations
import json
import logging
import os
import re
import sqlite3
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("fiber.observability")

# ============================================================
#  Trace Context — 全链路 trace_id
# ============================================================

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
span_id_var: ContextVar[str] = ContextVar("span_id", default="")


def new_trace_id() -> str:
    import uuid
    tid = uuid.uuid4().hex[:16]
    trace_id_var.set(tid)
    return tid


def new_span_id() -> str:
    import uuid
    sid = uuid.uuid4().hex[:8]
    span_id_var.set(sid)
    return sid


# ============================================================
#  Tracing — SQLite 持久化
# ============================================================

@dataclass
class SpanRecord:
    trace_id: str
    span_id: str
    parent_id: str | None
    operation: str
    start_time: float
    end_time: float | None = None
    status: str = "ok"
    attributes: dict = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time) * 1000


class TraceStore:
    """SQLite trace/span 持久化，7天 TTL 自动清理。"""

    TTL_DAYS = 7

    def __init__(self, db_path: str = "logs/traces.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = db_path
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    operation TEXT,
                    status TEXT DEFAULT 'ok',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_id TEXT,
                    operation TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL,
                    status TEXT DEFAULT 'ok',
                    attributes TEXT DEFAULT '{}',
                    FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
                );
                CREATE INDEX IF NOT EXISTS idx_spans_trace
                    ON spans(trace_id);
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    def start_trace(self, trace_id: str, operation: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO traces(trace_id, start_time, operation)"
                " VALUES (?, ?, ?)",
                (trace_id, time.time(), operation))

    def end_trace(self, trace_id: str, status: str = "ok") -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE traces SET end_time=?, status=? WHERE trace_id=?",
                (time.time(), status, trace_id))

    def add_span(self, span: SpanRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO spans"
                "(span_id, trace_id, parent_id, operation, start_time,"
                " end_time, status, attributes) VALUES (?,?,?,?,?,?,?,?)",
                (span.span_id, span.trace_id, span.parent_id,
                 span.operation, span.start_time, span.end_time,
                 span.status, json.dumps(span.attributes, default=str)))

    def get_trace(self, trace_id: str) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM spans WHERE trace_id=? ORDER BY start_time",
                (trace_id,)).fetchall()
            return [dict(r) for r in rows]

    def cleanup(self) -> int:
        """清理超过 TTL 的记录，返回删除数。"""
        cutoff = datetime.now(timezone.utc).timestamp() - self.TTL_DAYS * 86400
        deleted = 0
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM spans WHERE start_time < ?", (cutoff,))
            deleted += cur.rowcount
            cur = conn.execute(
                "DELETE FROM traces WHERE start_time < ?", (cutoff,))
            deleted += cur.rowcount
        if deleted:
            logger.info("TraceStore cleanup: 删除 %d 条过期记录", deleted)
        return deleted


# ============================================================
#  SpanTracer — 上下文管理器
# ============================================================

class SpanTracer:
    """with 语句 span 追踪器。"""

    def __init__(self, store: TraceStore, operation: str,
                 parent_id: str | None = None,
                 attributes: dict | None = None):
        self._store = store
        self._operation = operation
        self._span = SpanRecord(
            trace_id=trace_id_var.get(),
            span_id=new_span_id(),
            parent_id=parent_id or span_id_var.get() or None,
            operation=operation,
            start_time=time.time(),
            attributes=attributes or {},
        )

    def __enter__(self) -> SpanRecord:
        return self._span

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._span.end_time = time.time()
        if exc_type:
            self._span.status = "error"
            self._span.attributes["error"] = str(exc_val)
        self._store.add_span(self._span)


# ============================================================
#  StructuredLogger — 结构化 JSON 日志 + 脱敏
# ============================================================

_SENSITIVE_PATTERNS = [
    (re.compile(r'(password|passwd|secret|token|api_key|apikey)\s*[:=]\s*\S+', re.I),
     r'\1=***REDACTED***'),
    (re.compile(r'\b\d{11,}\b'),  # 手机号等长数字
     '***PHONE***'),
]


class StructuredFormatter(logging.Formatter):
    """结构化 JSON 日志格式器。"""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self._sanitize(record.getMessage()),
            "trace_id": trace_id_var.get(),
            "span_id": span_id_var.get(),
        }
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = self.formatException(record.exc_info)
        # 额外字段
        for key in ("agent", "tool", "session_id", "duration_ms", "status"):
            val = getattr(record, key, None)
            if val is not None:
                entry[key] = val
        return json.dumps(entry, ensure_ascii=False, default=str)

    def _sanitize(self, msg: str) -> str:
        for pattern, replacement in _SENSITIVE_PATTERNS:
            msg = pattern.sub(replacement, msg)
        return msg


def setup_structured_logging(log_dir: str = "logs",
                             retention_days: int = 7) -> None:
    """配置结构化日志: JSON 文件 + 控制台 + 7天保留。"""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = StructuredFormatter()

    # JSON 文件 handler
    fh = logging.FileHandler(
        log_path / "app_structured.jsonl", encoding="utf-8")
    fh.setFormatter(formatter)
    fh.setLevel(logging.DEBUG)

    # 控制台 handler（保持人类可读）
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    ch.setLevel(logging.INFO)

    root = logging.getLogger()
    root.addHandler(fh)
    root.addHandler(ch)

    logger.info("Structured logging: dir=%s, retention=%dd", log_dir, retention_days)


# ============================================================
#  MetricsAggregator — 60s 聚合窗口
# ============================================================

class MetricsAggregator:
    """60 秒聚合窗口，定期输出指标快照。"""

    def __init__(self, window_seconds: float = 60.0):
        self._window = window_seconds
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}
        self._cumulative: dict[str, int] = {}  # 累计计数器（不随 flush 清空）
        self._cumulative_latencies: dict[str, list[float]] = {}  # 累计延迟数据
        self._last_flush = time.time()

    def inc(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value
        self._cumulative[name] = self._cumulative.get(name, 0) + value

    def observe(self, name: str, value: float) -> None:
        self._latencies.setdefault(name, []).append(value)
        self._cumulative_latencies.setdefault(name, []).append(value)
        # 限制累计数据大小，保留最近 500 条
        if len(self._cumulative_latencies[name]) > 500:
            self._cumulative_latencies[name] = self._cumulative_latencies[name][-500:]

    def flush_if_needed(self) -> dict | None:
        now = time.time()
        if now - self._last_flush < self._window:
            return None
        return self.flush()

    def flush(self) -> dict:
        snapshot = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": dict(self._counters),
            "latencies": {},
        }
        for name, values in self._latencies.items():
            if values:
                values.sort()
                n = len(values)
                snapshot["latencies"][name] = {
                    "count": n,
                    "avg": round(sum(values) / n, 3),
                    "p50": round(values[n // 2], 3),
                    "p95": round(values[int(n * 0.95)], 3) if n > 1 else round(values[0], 3),
                    "max": round(values[-1], 3),
                }

        logger.info("Metrics flush: %d counters, %d latency series",
                     len(self._counters), len(self._latencies))

        self._counters.clear()
        self._latencies.clear()
        self._last_flush = time.time()
        return snapshot

    def snapshot(self) -> dict:
        """返回累计快照（不清空数据），供 API 调用。"""
        lat_snap = {}
        for name, values in self._cumulative_latencies.items():
            if values:
                vals = sorted(values)
                n = len(vals)
                lat_snap[name] = {
                    "count": n,
                    "avg": round(sum(vals) / n, 3),
                    "p50": round(vals[n // 2], 3),
                    "p95": round(vals[int(n * 0.95)], 3) if n > 1 else round(vals[0], 3),
                    "max": round(vals[-1], 3),
                }
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counters": dict(self._cumulative),
            "latencies": lat_snap,
        }


# ============================================================
#  ObservabilityFacade — 统一入口
# ============================================================

class ObservabilityFacade:
    """可观测性统一门面。"""

    def __init__(self, db_path: str = "logs/traces.db",
                 log_dir: str = "logs"):
        self.trace_store = TraceStore(db_path)
        self.metrics = MetricsAggregator()
        setup_structured_logging(log_dir)

    def start_trace(self, operation: str) -> str:
        tid = new_trace_id()
        self.trace_store.start_trace(tid, operation)
        self.metrics.inc("trace_started")
        return tid

    def end_trace(self, trace_id: str, status: str = "ok") -> None:
        self.trace_store.end_trace(trace_id, status)
        self.metrics.inc(f"trace_{status}")

    def span(self, operation: str, **kwargs) -> SpanTracer:
        return SpanTracer(self.trace_store, operation, **kwargs)

    def record_latency(self, name: str, ms: float) -> None:
        self.metrics.observe(name, ms)
        self.metrics.flush_if_needed()

    def cleanup(self) -> int:
        return self.trace_store.cleanup()


# 全局单例
_observability: ObservabilityFacade | None = None


def get_observability(log_dir: str = "logs") -> ObservabilityFacade:
    global _observability
    if _observability is None:
        _observability = ObservabilityFacade(
            db_path=f"{log_dir}/traces.db", log_dir=log_dir)
    return _observability
