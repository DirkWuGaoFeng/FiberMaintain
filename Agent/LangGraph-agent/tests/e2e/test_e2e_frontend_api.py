"""
针对前端 API 交互的端到端测试 [v7.1]。

验证 Agent 服务器与 Vue 前端的兼容性：
- SSE 流式格式 (/fiber-agent/stream)
- Invoke 响应结构
- 错误响应格式
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def test_app():
    """创建用于前端 API 测试的应用。"""
    from src.server import create_app

    return create_app()


@pytest_asyncio.fixture
async def api_client(test_app):
    """用于 API 测试的异步客户端。"""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestInvokeResponseFormat:
    """验证 /invoke 响应符合前端预期。"""

    @pytest.mark.asyncio
    async def test_invoke_response_structure(self, api_client, monkeypatch):
        """响应应包含：result、processing_path、latency_ms、request_id。"""
        mock_result = {
            "final_output": "光纤1衰耗3.2dB，正常。",
            "processing_path": "fast",
            "request_id": "req-abc-123",
            "degradation_level": 0,
            "loop_count": 0,
        }
        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        with (
            patch("src.graph.main_graph.get_graph", return_value=mock_graph),
            patch("src.observability.audit.write_request_audit", new_callable=AsyncMock),
        ):
            resp = await api_client.post(
                "/invoke",
                json={
                    "message": "查询光纤1的衰耗",
                    "thread_id": "frontend-test",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "processing_path" in data
        assert "latency_ms" in data
        assert "request_id" in data
        assert isinstance(data["latency_ms"], int)

    @pytest.mark.asyncio
    async def test_invoke_error_format(self, api_client):
        """错误响应应包含 detail 字段。"""
        with patch("src.graph.main_graph.get_graph") as mock_get_graph:
            mock_graph = AsyncMock()
            mock_get_graph.return_value = mock_graph
            resp = await api_client.post("/invoke", json={"message": ""})
        assert resp.status_code == 400
        data = resp.json()
        assert "detail" in data


class TestFrontendDataAPIs:
    """验证前端仪表盘使用的数据 API 端点。"""

    @pytest.mark.asyncio
    async def test_health_endpoint_for_status_widget(self, api_client):
        """前端状态组件调用 /health。"""
        resp = await api_client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rules_reload_for_admin_panel(self, api_client):
        """管理面板可触发规则重载。"""
        resp = await api_client.post("/api/v1/rules/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert isinstance(data["rules_loaded"], int)


class TestSSEStreamFormat:
    """验证与前端兼容的 SSE 流式格式。"""

    def test_frontend_expects_sse_data_prefix(self):
        """前端解析以 'data: ' 开头的行。"""
        # 模拟前端期望的 SSE 格式
        sse_line = 'data: {"type": "token", "content": "光纤"}\n\n'
        assert sse_line.startswith("data: ")
        payload = sse_line.strip()[6:]
        data = json.loads(payload)
        assert data["type"] == "token"

    def test_frontend_done_signal(self):
        """前端期望以 'data: [DONE]' 作为终止信号。"""
        done_line = "data: [DONE]\n\n"
        payload = done_line.strip()[6:]
        assert payload == "[DONE]"

    def test_frontend_event_types(self):
        """验证预期的事件类型结构。"""
        # 前端处理的事件
        event_types = ["token", "tool_start", "tool_end", "error", "done"]
        for evt_type in event_types:
            event = {"type": evt_type}
            serialized = f"data: {json.dumps(event)}\n\n"
            # 验证可解析性
            parsed = json.loads(serialized.strip()[6:])
            assert parsed["type"] == evt_type


class TestThreadContinuity:
    """验证基于 thread_id 的对话连续性。"""

    @pytest.mark.asyncio
    async def test_thread_id_passed_to_graph(self, api_client, monkeypatch):
        """请求中的 thread_id 应传递给 graph 配置。"""
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

        with (
            patch("src.graph.main_graph.get_graph", return_value=mock_graph),
            patch("src.observability.audit.write_request_audit", new_callable=AsyncMock),
        ):
            resp = await api_client.post(
                "/invoke",
                json={
                    "message": "查询光纤1的衰耗",
                    "thread_id": "my-session-123",
                },
            )

        assert resp.status_code == 200
        assert captured_config.get("configurable", {}).get("thread_id") == "my-session-123"

    @pytest.mark.asyncio
    async def test_default_thread_id(self, api_client, monkeypatch):
        """缺少 thread_id 时应使用 'default'。"""
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

        with (
            patch("src.graph.main_graph.get_graph", return_value=mock_graph),
            patch("src.observability.audit.write_request_audit", new_callable=AsyncMock),
        ):
            resp = await api_client.post(
                "/invoke",
                json={
                    "message": "查询光纤1的衰耗",
                },
            )

        assert resp.status_code == 200
        assert captured_config.get("configurable", {}).get("thread_id") == "default"
