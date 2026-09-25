"""
Trace 诊断 API 集成测试 [v7.2]。

使用 FastAPI TestClient（独立数据目录）测试 /api/v1/traces 和
/api/v1/traces/{trace_id} 端点。
"""

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.observability.request_tracer import RequestTracer, _recent_traces


@pytest.fixture
def trace_app(tmp_path):
    """创建一个带 trace 端点的最小 FastAPI 应用用于测试。"""
    from fastapi import HTTPException

    app = FastAPI()
    traces_dir = tmp_path / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/api/v1/traces")
    async def list_traces(limit: int = 20):
        from src.observability.request_tracer import get_recent_traces

        return {"traces": get_recent_traces(limit)}

    @app.get("/api/v1/traces/{trace_id}")
    async def get_trace_detail(trace_id: str):
        trace_file = traces_dir / f"{trace_id}.json"
        if not trace_file.exists():
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
        try:
            return json.loads(trace_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return app, traces_dir


@pytest.fixture
def client(trace_app):
    """trace 应用的 TestClient。"""
    app, _ = trace_app
    return TestClient(app)


class TestListTraces:
    """测试 GET /api/v1/traces 端点。"""

    def test_list_traces_empty(self, client):
        """无 trace → 空列表。"""
        # 清空 deque 以保证隔离
        _recent_traces.clear()
        resp = client.get("/api/v1/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert "traces" in data
        assert isinstance(data["traces"], list)

    def test_list_traces_with_data(self, client, tmp_path):
        """创建 tracer → 结束 → API 返回摘要。"""
        _recent_traces.clear()
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            tracer = RequestTracer(user_input="API测试查询", trace_id="api-test-01")
            with tracer.span("rule_engine") as span:
                span.set_output("match=R001")
            tracer.finish(processing_path="fast", final_output="结果正常")

        resp = client.get("/api/v1/traces")
        assert resp.status_code == 200
        traces = resp.json()["traces"]
        found = [t for t in traces if t["trace_id"] == "api-test-01"]
        assert len(found) == 1
        assert found[0]["user_input"] == "API测试查询"
        assert found[0]["processing_path"] == "fast"
        assert found[0]["status"] == "SUCCESS"

    def test_trace_limit_param(self, client):
        """limit 参数限制返回条数。"""
        _recent_traces.clear()
        # 添加多条 trace
        for i in range(5):
            _recent_traces.append(
                {
                    "trace_id": f"limit-{i}",
                    "user_input": f"test {i}",
                    "processing_path": "fast",
                    "total_ms": 100.0,
                    "status": "SUCCESS",
                    "slow_spans": [],
                    "timestamp": "2026-08-01T00:00:00",
                }
            )

        resp = client.get("/api/v1/traces?limit=3")
        assert resp.status_code == 200
        traces = resp.json()["traces"]
        assert len(traces) == 3


class TestGetTraceDetail:
    """测试 GET /api/v1/traces/{trace_id} 端点。"""

    def test_get_trace_detail(self, trace_app):
        """写入的 trace 文件可按 ID 查询。"""
        app, traces_dir = trace_app
        client = TestClient(app)

        # 手动写入一个 trace 文件
        trace_data = {
            "trace_id": "detail-001",
            "user_input": "详细查询",
            "processing_path": "normal",
            "total_ms": 1500.0,
            "span_count": 3,
            "status": "SUCCESS",
            "slow_spans": [],
            "phase_breakdown": [
                {"node": "rule_engine", "duration_ms": 5.0, "percentage": 0.3, "is_slow": False},
                {"node": "intent_classifier", "duration_ms": 1200.0, "percentage": 80.0, "is_slow": False},
            ],
            "final_output": "光纤状态正常",
            "spans": [],
            "timestamp": "2026-08-01T10:00:00",
        }
        trace_file = traces_dir / "detail-001.json"
        trace_file.write_text(json.dumps(trace_data, ensure_ascii=False), encoding="utf-8")

        resp = client.get("/api/v1/traces/detail-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == "detail-001"
        assert data["total_ms"] == 1500.0
        assert len(data["phase_breakdown"]) == 2

    def test_get_trace_not_found(self, client):
        """不存在的 trace_id 返回 404。"""
        resp = client.get("/api/v1/traces/nonexistent-id")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_get_trace_invalid_json(self, trace_app):
        """损坏的 trace 文件返回 500。"""
        app, traces_dir = trace_app
        client = TestClient(app)

        # 写入非法 JSON
        bad_file = traces_dir / "bad-trace.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")

        resp = client.get("/api/v1/traces/bad-trace")
        assert resp.status_code == 500
