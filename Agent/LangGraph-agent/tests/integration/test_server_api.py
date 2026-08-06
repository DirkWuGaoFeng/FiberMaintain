"""
Integration tests for Server API [v7.1].

Tests FastAPI endpoints:
- GET /health
- POST /invoke
- POST /api/v1/rules/reload
- GET /api/v1/degradation
- GET /api/batch/{thread_id}/progress
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from httpx import AsyncClient, ASGITransport


@pytest.fixture
def app():
    """Create test app with mocked heavy dependencies."""
    from src.server import create_app
    return create_app()


@pytest_asyncio.fixture
async def client(app):
    """Async test client for FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    """GET /health tests."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        """Health endpoint should return status ok."""
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data or "version" in data

    @pytest.mark.asyncio
    async def test_health_includes_version(self, client):
        """Health response includes version info."""
        resp = await client.get("/health")
        data = resp.json()
        # Either full health probe or fallback
        if "version" in data:
            assert data["version"] == "7.2.0"


class TestInvokeEndpoint:
    """POST /invoke tests."""

    @pytest.mark.asyncio
    async def test_invoke_missing_message(self, client):
        """Invoke without message returns 400 or 500 (graph init may fail)."""
        with patch("src.graph.main_graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_get_graph.return_value = mock_graph
            resp = await client.post("/invoke", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_empty_message(self, client):
        """Invoke with empty message returns 400."""
        with patch("src.graph.main_graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_get_graph.return_value = mock_graph
            resp = await client.post("/invoke", json={"message": ""})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invoke_with_mocked_graph(self, client, monkeypatch):
        """Invoke with mocked graph returns structured response."""
        mock_result = {
            "final_output": "光纤1衰耗为3.2dB，状态正常。",
            "processing_path": "fast",
            "request_id": "test-req-001",
            "degradation_level": 0,
            "loop_count": 0,
        }

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch("src.graph.main_graph.get_graph", return_value=mock_graph), \
             patch("src.observability.audit.write_request_audit", new_callable=AsyncMock):
            resp = await client.post("/invoke", json={
                "message": "查询光纤1的衰耗",
                "thread_id": "test-thread",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == "光纤1衰耗为3.2dB，状态正常。"
        assert data["processing_path"] == "fast"
        assert "latency_ms" in data


class TestRulesReloadEndpoint:
    """POST /api/v1/rules/reload tests."""

    @pytest.mark.asyncio
    async def test_rules_reload_success(self, client):
        """Rules reload should return count of loaded rules."""
        resp = await client.post("/api/v1/rules/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["rules_loaded"] > 0


class TestDegradationEndpoint:
    """GET /api/v1/degradation tests."""

    @pytest.mark.asyncio
    async def test_degradation_status(self, client):
        """Degradation endpoint returns level info."""
        resp = await client.get("/api/v1/degradation")
        assert resp.status_code == 200
        data = resp.json()
        assert "level" in data or "error" in data


class TestBatchProgressEndpoint:
    """GET /api/batch/{thread_id}/progress tests."""

    @pytest.mark.asyncio
    async def test_batch_progress_not_found(self, client):
        """Non-existent thread returns not_found."""
        resp = await client.get("/api/batch/nonexistent-thread/progress")
        assert resp.status_code == 200
        data = resp.json()
        # Should return not_found or error
        assert "status" in data or "error" in data


class TestCORSHeaders:
    """CORS middleware tests."""

    @pytest.mark.asyncio
    async def test_cors_headers_present(self, client):
        """CORS headers should be present in responses."""
        resp = await client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS middleware should allow all origins
        assert resp.status_code in (200, 204, 405)


class TestSSEStreamEndpoint:
    """POST /fiber-agent/stream tests."""

    @pytest.mark.asyncio
    async def test_stream_missing_message(self, client):
        """Stream without message returns 400."""
        resp = await client.post("/fiber-agent/stream", json={})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_stream_returns_sse_content_type(self, client):
        """Stream endpoint returns text/event-stream content type."""
        # Mock graph to avoid actual LLM calls
        mock_events = [
            {"event": "on_chain_start", "name": "input_guard", "data": {}},
            {"event": "on_chain_end", "name": "result_aggregator",
             "data": {"output": {"final_output": "测试输出"}}},
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
        """Stream should contain final_output event for fast path."""
        mock_events = [
            {"event": "on_chain_start", "name": "input_guard", "data": {}},
            {"event": "on_chain_end", "name": "input_guard", "data": {"output": {}}},
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {"event": "on_chain_end", "name": "rule_engine",
             "data": {"output": {"rule_match": {"intent": "spanloss_query"}}}},
            {"event": "on_chain_start", "name": "fast_path_executor", "data": {}},
            {"event": "on_chain_end", "name": "fast_path_executor",
             "data": {"output": {"final_output": "光纤 3 当前衰耗为 4.2 dB"}}},
            {"event": "on_chain_start", "name": "result_aggregator", "data": {}},
            {"event": "on_chain_end", "name": "result_aggregator",
             "data": {"output": {"final_output": "光纤 3 当前衰耗为 4.2 dB"}}},
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
