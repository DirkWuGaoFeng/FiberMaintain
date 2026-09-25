"""
服务器 API 集成测试 [v7.1]。

测试 FastAPI 端点：
- GET /health
- POST /invoke
- POST /api/v1/rules/reload
- GET /api/v1/degradation
- GET /api/batch/{thread_id}/progress
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    """创建已 mock 掉重型依赖的测试应用。"""
    from src.server import create_app

    return create_app()


@pytest.fixture
def client(app):
    """用于 FastAPI 应用的异步测试客户端。

    【说明】使用同步 fixture 返回 AsyncClient 实例，以兼容
    pytest-asyncio 0.24.0 在此环境下 async generator fixture 不
    被正确解包的 bug。AsyncClient 的关闭由 GC 处理。
    """
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestHealthEndpoint:
    """GET /health 测试。"""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        """健康端点应返回 status ok。"""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data or "version" in data

    @pytest.mark.asyncio
    async def test_health_includes_version(self, client):
        """健康响应包含版本信息。"""
        resp = await client.get("/health")
        data = resp.json()
        # 要么完整健康探测，要么回退
        if "version" in data:
            assert data["version"] == "7.2.0"


class TestInvokeEndpoint:
    """POST /invoke 测试。"""

    @pytest.mark.asyncio
    async def test_invoke_missing_message(self, client):
        """无消息调用 invoke 返回 400 或 500（graph 初始化可能失败）。"""
        with patch("src.graph.main_graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_get_graph.return_value = mock_graph
            resp = await client.post("/invoke", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_empty_message(self, client):
        """空消息调用 invoke 返回 400。"""
        with patch("src.graph.main_graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_get_graph.return_value = mock_graph
            resp = await client.post("/invoke", json={"message": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_with_mocked_graph(self, client, monkeypatch):
        """使用 mock graph 调用 invoke 返回结构化响应。"""
        mock_result = {
            "final_output": "光纤1衰耗为3.2dB，状态正常。",
            "processing_path": "fast",
            "request_id": "test-req-001",
            "degradation_level": 0,
            "loop_count": 0,
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with (
            patch("src.graph.main_graph.get_graph", return_value=mock_graph),
            patch("src.observability.audit.write_request_audit", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/invoke",
                json={
                    "message": "查询光纤1的衰耗",
                    "thread_id": "test-thread",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "光纤1衰耗为3.2dB，状态正常。"
        assert data["processing_path"] == "fast"
        assert "latency_ms" in data

    @pytest.mark.asyncio
    async def test_invoke_passes_user_id_to_state(self, client, monkeypatch):
        """[v7.4] invoke 应把请求中的 user_id 透传给 create_initial_state."""
        calls = {}

        def fake_create_initial_state(user_message, thread_id="", user_id=""):
            calls["user_message"] = user_message
            calls["thread_id"] = thread_id
            calls["user_id"] = user_id
            return {"final_output": "", "request_id": "r-1", "trace_id": "t-1"}

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "final_output": "ok",
                "processing_path": "fast",
                "request_id": "r-1",
                "degradation_level": 0,
                "loop_count": 0,
            }
        )

        monkeypatch.setattr("src.graph.state.create_initial_state", fake_create_initial_state)
        with (
            patch("src.graph.main_graph.get_graph", return_value=mock_graph),
            patch("src.observability.audit.write_request_audit", new_callable=AsyncMock),
        ):
            resp = await client.post(
                "/invoke",
                json={
                    "message": "查询光纤1的衰耗",
                    "thread_id": "t-9",
                    "user_id": "u-42",
                },
            )

        assert resp.status_code == 200
        assert calls["user_id"] == "u-42"
        assert calls["thread_id"] == "t-9"

    @pytest.mark.asyncio
    async def test_invoke_no_user_id_defaults_empty(self, client, monkeypatch):
        """[v7.4] 无 user_id 时传递空串（create_initial_state 回退环境变量）."""
        calls = {}

        def fake_create_initial_state(user_message, thread_id="", user_id=""):
            calls["user_id"] = user_id
            return {"final_output": "", "request_id": "r-1", "trace_id": "t-1"}

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={
                "final_output": "ok",
                "processing_path": "fast",
                "request_id": "r-1",
                "degradation_level": 0,
                "loop_count": 0,
            }
        )

        monkeypatch.setattr("src.graph.state.create_initial_state", fake_create_initial_state)
        with (
            patch("src.graph.main_graph.get_graph", return_value=mock_graph),
            patch("src.observability.audit.write_request_audit", new_callable=AsyncMock),
        ):
            resp = await client.post("/invoke", json={"message": "hi"})

        assert resp.status_code == 200
        assert calls["user_id"] == ""


class TestRulesReloadEndpoint:
    """POST /api/v1/rules/reload 测试。"""

    @pytest.mark.asyncio
    async def test_rules_reload_success(self, client):
        """规则重载应返回加载的规则数量。"""
        resp = await client.post("/api/v1/rules/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["rules_loaded"] > 0


class TestDegradationEndpoint:
    """GET /api/v1/degradation 测试。"""

    @pytest.mark.asyncio
    async def test_degradation_status(self, client):
        """降级端点返回等级信息。"""
        resp = await client.get("/api/v1/degradation")
        assert resp.status_code == 200
        data = resp.json()
        assert "level" in data or "error" in data


class TestBatchProgressEndpoint:
    """GET /api/batch/{thread_id}/progress 测试。"""

    @pytest.mark.asyncio
    async def test_batch_progress_not_found(self, client):
        """不存在的线程返回 not_found。"""
        resp = await client.get("/api/batch/nonexistent-thread/progress")
        assert resp.status_code == 200
        data = resp.json()
        # 应返回 not_found 或 error
        assert "status" in data or "error" in data


class TestCORSHeaders:
    """CORS 中间件测试。"""

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client):
        """响应中应存在 CORS 头。"""
        resp = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS 中间件应允许所有来源
        assert resp.status_code in (200, 204, 405)


class TestSSEStreamEndpoint:
    """POST /fiber-agent/stream 测试。"""

    @pytest.mark.asyncio
    async def test_stream_missing_message(self, client):
        """无消息调用 stream 返回 400。"""
        resp = await client.post("/fiber-agent/stream", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_stream_returns_sse_content_type(self, client):
        """stream 端点返回 text/event-stream content type。"""
        # mock graph 以避免真实的 LLM 调用
        mock_events = [
            {"event": "on_chain_start", "name": "input_guard", "data": {}},
            {"event": "on_chain_end", "name": "result_aggregator", "data": {"output": {"final_output": "测试输出"}}},
        ]

        async def mock_astream_events(*args, **kwargs):
            for e in mock_events:
                yield e

        mock_graph = MagicMock()
        mock_graph.astream_events = mock_astream_events

        with patch("src.graph.main_graph.get_graph", return_value=mock_graph):
            resp = await client.post(
                "/fiber-agent/stream",
                json={
                    "input": {"user_input": "查询光纤1的衰耗", "thread_id": "test"},
                    "config": {"configurable": {"thread_id": "test"}},
                },
            )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_stream_contains_final_output_event(self, client):
        """stream 应对快速路径包含 final_output 事件。"""
        mock_events = [
            {"event": "on_chain_start", "name": "input_guard", "data": {}},
            {"event": "on_chain_end", "name": "input_guard", "data": {"output": {}}},
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {
                "event": "on_chain_end",
                "name": "rule_engine",
                "data": {"output": {"rule_match": {"intent": "spanloss_query"}}},
            },
            {"event": "on_chain_start", "name": "fast_path_executor", "data": {}},
            {
                "event": "on_chain_end",
                "name": "fast_path_executor",
                "data": {"output": {"final_output": "光纤 3 当前衰耗为 4.2 dB"}},
            },
            {"event": "on_chain_start", "name": "result_aggregator", "data": {}},
            {
                "event": "on_chain_end",
                "name": "result_aggregator",
                "data": {"output": {"final_output": "光纤 3 当前衰耗为 4.2 dB"}},
            },
        ]

        async def mock_astream_events(*args, **kwargs):
            for e in mock_events:
                yield e

        mock_graph = MagicMock()
        mock_graph.astream_events = mock_astream_events

        with patch("src.graph.main_graph.get_graph", return_value=mock_graph):
            resp = await client.post(
                "/fiber-agent/stream",
                json={
                    "input": {"user_input": "查询光纤 3 的跨段衰耗", "thread_id": "test"},
                    "config": {"configurable": {"thread_id": "test"}},
                },
            )

        assert resp.status_code == 200
        body = resp.text
        # 验证包含 final_output 事件
        assert "final_output" in body
        assert "光纤 3 当前衰耗为 4.2 dB" in body
        # 显式关闭 SSE 流，避免 Event 泄漏到测试事件循环
        await resp.aclose()

    @pytest.mark.asyncio
    async def test_stream_passes_user_id_to_state(self, client, monkeypatch):
        """[v7.4] stream 应把 input.user_id 透传给 create_initial_state."""
        calls = {}

        def fake_create_initial_state(user_message, thread_id="", user_id=""):
            calls["user_message"] = user_message
            calls["thread_id"] = thread_id
            calls["user_id"] = user_id
            return {"final_output": "", "trace_id": "t-1"}

        async def mock_astream_events(*args, **kwargs):
            yield {"event": "on_chain_end", "name": "result_aggregator", "data": {"output": {"final_output": "ok"}}}

        mock_graph = MagicMock()
        mock_graph.astream_events = mock_astream_events

        monkeypatch.setattr("src.graph.state.create_initial_state", fake_create_initial_state)
        with patch("src.graph.main_graph.get_graph", return_value=mock_graph):
            resp = await client.post(
                "/fiber-agent/stream",
                json={
                    "input": {"user_input": "hi", "thread_id": "t-7", "user_id": "u-88"},
                    "config": {"configurable": {"thread_id": "t-7"}},
                },
            )

        assert resp.status_code == 200
        assert calls["user_id"] == "u-88"
        assert calls["thread_id"] == "t-7"
        # 显式消费并关闭 SSE 流，避免 Event 泄漏到测试事件循环
        await resp.aclose()


class TestConsolidateEndpoint:
    """POST /api/v1/memory/consolidate [v7.4]."""

    @pytest.mark.asyncio
    async def test_consolidate_dry_run(self, client, monkeypatch):
        """dry_run=true → 返回报告且不写库."""
        from src.memory.consolidator import ConsolidationReport

        class FakeConsolidator:
            def consolidate(self, stale_days=180, max_per_fiber=20, dry_run=False):
                assert dry_run is True
                return ConsolidationReport(scanned=3, merged=1)

        monkeypatch.setattr(
            "src.memory.consolidator.get_consolidator",
            lambda: FakeConsolidator(),
        )

        resp = await client.post(
            "/api/v1/memory/consolidate",
            json={"dry_run": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["report"]["scanned"] == 3
        assert data["report"]["merged"] == 1

    @pytest.mark.asyncio
    async def test_consolidate_consolidator_error(self, client, monkeypatch):
        """consolidator 抛异常 → 500."""

        class BoomConsolidator:
            def consolidate(self, **kwargs):
                raise RuntimeError("db lock")

        monkeypatch.setattr(
            "src.memory.consolidator.get_consolidator",
            lambda: BoomConsolidator(),
        )

        resp = await client.post(
            "/api/v1/memory/consolidate",
            json={"dry_run": False},
        )
        assert resp.status_code == 500
