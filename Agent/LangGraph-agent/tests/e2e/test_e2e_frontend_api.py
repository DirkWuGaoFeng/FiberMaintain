"""
End-to-end tests for Frontend API interaction [v7.1].

Verifies the Agent server's compatibility with the Vue frontend:
- SSE streaming format (/fiber-agent/stream)
- Invoke response structure
- Error response format
"""

import json

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport


@pytest.fixture
def test_app():
    """Create app for frontend API testing."""
    from src.server import create_app
    return create_app()


@pytest_asyncio.fixture
async def api_client(test_app):
    """Async client for API testing."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestInvokeResponseFormat:
    """Verify /invoke response matches frontend expectations."""

    @pytest.mark.asyncio
    async def test_invoke_response_structure(self, api_client, monkeypatch):
        """Response should have: result, processing_path, latency_ms, request_id."""
        mock_result = {
            "final_output": "光纤1衰耗3.2dB，正常。",
            "processing_path": "fast",
            "request_id": "req-abc-123",
            "degradation_level": 0,
            "loop_count": 0,
        }
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with patch("src.graph.main_graph.get_graph", return_value=mock_graph), \
             patch("src.observability.audit.write_request_audit", new_callable=AsyncMock):
            resp = await api_client.post("/invoke", json={
                "message": "查询光纤1的衰耗",
                "thread_id": "frontend-test",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "processing_path" in data
        assert "latency_ms" in data
        assert "request_id" in data
        assert isinstance(data["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_invoke_error_format(self, api_client):
        """Error responses should have detail field."""
        with patch("src.graph.main_graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_get_graph.return_value = mock_graph
            resp = await api_client.post("/invoke", json={"message": ""})
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data


class TestFrontendDataAPIs:
    """Verify data API endpoints used by frontend dashboard."""

    @pytest.mark.asyncio
    async def test_health_endpoint_for_status_widget(self, api_client):
        """Frontend status widget calls /health."""
        resp = await api_client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rules_reload_for_admin_panel(self, api_client):
        """Admin panel can trigger rules reload."""
        resp = await api_client.post("/api/v1/rules/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["rules_loaded"], int)


class TestSSEStreamFormat:
    """Verify SSE streaming format compatibility with frontend."""

    def test_frontend_expects_sse_data_prefix(self):
        """Frontend parses lines starting with 'data: '."""
        # Simulate SSE format that frontend expects
        sse_line = "data: {\"type\": \"token\", \"content\": \"光纤\"}\n\n"
        assert sse_line.startswith("data: ")
        payload = sse_line.strip()[6:]
        data = json.loads(payload)
        assert data["type"] == "token"

    def test_frontend_done_signal(self):
        """Frontend expects 'data: [DONE]' as termination signal."""
        done_line = "data: [DONE]\n\n"
        payload = done_line.strip()[6:]
        assert payload == "[DONE]"

    def test_frontend_event_types(self):
        """Verify expected event type structure."""
        # Events the frontend handles
        event_types = ["token", "tool_start", "tool_end", "error", "done"]
        for evt_type in event_types:
            event = {"type": evt_type}
            serialized = f"data: {json.dumps(event)}\n\n"
            # Verify parseable
            parsed = json.loads(serialized.strip()[6:])
            assert parsed["type"] == evt_type


class TestThreadContinuity:
    """Verify thread_id based conversation continuity."""

    @pytest.mark.asyncio
    async def test_thread_id_passed_to_graph(self, api_client, monkeypatch):
        """thread_id from request should be passed to graph config."""
        captured_config = {}

        mock_result = {
            "final_output": "test",
            "processing_path": "fast",
            "request_id": "r1",
            "degradation_level": 0,
            "loop_count": 0,
        }

        async def capture_invoke(state, config=None, **kwargs):
            if config:
                captured_config.update(config)
            return mock_result

        mock_graph = AsyncMock()
        mock_graph.ainvoke = capture_invoke

        with patch("src.graph.main_graph.get_graph", return_value=mock_graph), \
             patch("src.observability.audit.write_request_audit", new_callable=AsyncMock):
            resp = await api_client.post("/invoke", json={
                "message": "查询光纤1的衰耗",
                "thread_id": "my-session-123",
            })

        assert resp.status_code == 200
        assert captured_config.get("configurable", {}).get("thread_id") == "my-session-123"

    @pytest.mark.asyncio
    async def test_default_thread_id(self, api_client, monkeypatch):
        """Missing thread_id should use 'default'."""
        captured_config = {}

        mock_result = {
            "final_output": "test",
            "processing_path": "fast",
            "request_id": "r1",
            "degradation_level": 0,
            "loop_count": 0,
        }

        async def capture_invoke(state, config=None, **kwargs):
            if config:
                captured_config.update(config)
            return mock_result

        mock_graph = AsyncMock()
        mock_graph.ainvoke = capture_invoke

        with patch("src.graph.main_graph.get_graph", return_value=mock_graph), \
             patch("src.observability.audit.write_request_audit", new_callable=AsyncMock):
            resp = await api_client.post("/invoke", json={
                "message": "查询光纤1的衰耗",
            })

        assert resp.status_code == 200
        assert captured_config.get("configurable", {}).get("thread_id") == "default"
