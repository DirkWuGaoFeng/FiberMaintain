"""
SSE 超时、心跳与 tracer 集成测试 [v7.2]。

测试：
- 长时间运行请求期间的心跳发射
- 带 trace_id 的超时错误事件
- 带 final_output 事件的正常完成
- 请求完成后的 tracer 文件生成

使用 mock graph 模拟各种 SSE 场景，无需真实 LLM/后端。
"""

import asyncio
import json
import time
from unittest.mock import patch

# =============================================================================
# 辅助：模拟 SSE 事件生成器逻辑（从 server.py 提取）
# =============================================================================


async def simulate_sse_stream(
    events: list[dict],
    stream_timeout: float = 120.0,
    heartbeat_interval: float = 5.0,
    delay_per_event: float = 0.0,
):
    """
    模拟 server.py 中的 SSE 事件生成器逻辑。

    产出 SSE 事件字典（与 server.py event_generator 格式相同）。
    """
    from src.observability.request_tracer import RequestTracer

    tracer = RequestTracer(user_input="test query", trace_id="sse-test-001")
    start_time = time.time()
    last_heartbeat = start_time
    final_output = ""
    processing_path = "normal"

    try:
        async with asyncio.timeout(stream_timeout):
            for event in events:
                if delay_per_event > 0:
                    await asyncio.sleep(delay_per_event)

                now = time.time()

                # 捕获 final_output
                if event.get("event") == "on_chain_end" and event.get("name") in (
                    "result_aggregator",
                    "fast_path_executor",
                ):
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict) and output.get("final_output"):
                        final_output = output["final_output"]
                    if isinstance(output, dict) and output.get("processing_path"):
                        processing_path = output["processing_path"]

                # 心跳
                if now - last_heartbeat >= heartbeat_interval:
                    elapsed_ms = int((now - start_time) * 1000)
                    heartbeat = {
                        "event": "heartbeat",
                        "data": {"elapsed_ms": elapsed_ms, "status": "processing"},
                    }
                    yield heartbeat
                    last_heartbeat = now

                yield event

        # 最终输出事件
        if final_output:
            yield {
                "event": "final_output",
                "data": {"output": final_output},
            }

        tracer.finish(processing_path=processing_path, final_output=final_output)

    except asyncio.TimeoutError:
        elapsed_ms = int((time.time() - start_time) * 1000)
        tracer.finish(processing_path="timeout", final_output="")
        yield {
            "event": "error",
            "data": {
                "message": f"Request timeout ({stream_timeout}s)",
                "elapsed_ms": elapsed_ms,
                "code": "TIMEOUT",
                "trace_id": tracer.trace_id,
            },
        }

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        tracer.finish(processing_path="error", final_output="")
        yield {
            "event": "error",
            "data": {
                "message": str(e),
                "elapsed_ms": elapsed_ms,
                "code": "INTERNAL_ERROR",
                "trace_id": tracer.trace_id,
            },
        }


class TestSSEHeartbeat:
    """测试长时间运行请求期间的心跳发射。"""

    async def test_sse_heartbeat_emission(self):
        """长时间运行的请求会发射心跳事件。"""
        # 模拟带延迟的事件以触发心跳
        events = [
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {}}},
            {"event": "on_chain_start", "name": "intent_classifier", "data": {}},
            {"event": "on_chain_end", "name": "intent_classifier", "data": {"output": {}}},
        ]

        collected = []
        # 使用非常短的心跳间隔以在测试中触发
        async for event in simulate_sse_stream(events, heartbeat_interval=0.01, delay_per_event=0.02):
            collected.append(event)

        # 应混合有心跳事件
        heartbeats = [e for e in collected if e.get("event") == "heartbeat"]
        # 4 个事件 * 0.02s 延迟 + 0.01s 心跳间隔，期望至少 1 个
        assert len(heartbeats) >= 1
        # 心跳结构正确
        hb = heartbeats[0]
        assert "elapsed_ms" in hb["data"]
        assert hb["data"]["status"] == "processing"

    async def test_no_heartbeat_for_fast_requests(self):
        """快速请求不发射心跳。"""
        events = [
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {}}},
        ]

        collected = []
        async for event in simulate_sse_stream(events, heartbeat_interval=5.0):
            collected.append(event)

        heartbeats = [e for e in collected if e.get("event") == "heartbeat"]
        assert len(heartbeats) == 0


class TestSSETimeout:
    """测试超时错误事件。"""

    async def test_sse_timeout_error_event(self):
        """超时产生带 trace_id 的错误事件。"""
        # 创建一个会"挂起"的事件列表（用长延迟模拟）
        events = [{"event": "on_chain_start", "name": "data_collector", "data": {}}]

        collected = []
        # 非常短的超时以在测试中触发
        async for event in simulate_sse_stream(events, stream_timeout=0.05, delay_per_event=0.1):
            collected.append(event)

        # 应产生超时错误事件
        errors = [e for e in collected if e.get("event") == "error"]
        assert len(errors) == 1
        err = errors[0]
        assert err["data"]["code"] == "TIMEOUT"
        assert "trace_id" in err["data"]
        assert err["data"]["trace_id"] == "sse-test-001"
        assert err["data"]["elapsed_ms"] > 0

    async def test_sse_timeout_message_format(self):
        """超时消息包含超时时长。"""
        events = [{"event": "on_chain_start", "name": "analysis_expert", "data": {}}]

        collected = []
        async for event in simulate_sse_stream(events, stream_timeout=0.05, delay_per_event=0.1):
            collected.append(event)

        errors = [e for e in collected if e.get("event") == "error"]
        assert len(errors) == 1
        assert "0.05s" in errors[0]["data"]["message"]


class TestSSENormalCompletion:
    """测试带 final_output 的正常完成。"""

    async def test_sse_normal_completion(self):
        """正常请求发射 final_output 事件。"""
        events = [
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
                "data": {"output": {"final_output": "光纤1衰耗3.2dB正常", "processing_path": "fast"}},
            },
        ]

        collected = []
        async for event in simulate_sse_stream(events):
            collected.append(event)

        # 应产生 final_output 事件
        finals = [e for e in collected if e.get("event") == "final_output"]
        assert len(finals) == 1
        assert finals[0]["data"]["output"] == "光纤1衰耗3.2dB正常"

    async def test_sse_no_final_output_without_result(self):
        """若无 result_aggregator/fast_path 输出，则不产生 final_output 事件。"""
        events = [
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {}}},
        ]

        collected = []
        async for event in simulate_sse_stream(events):
            collected.append(event)

        finals = [e for e in collected if e.get("event") == "final_output"]
        assert len(finals) == 0


class TestSSETracerIntegration:
    """测试 tracer 与 SSE 流的集成。"""

    async def test_sse_tracer_integration(self, tmp_path):
        """请求完成生成 trace 文件。"""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            events = [
                {"event": "on_chain_start", "name": "rule_engine", "data": {}},
                {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {}}},
            ]

            collected = []
            async for event in simulate_sse_stream(events):
                collected.append(event)

            # trace 文件应存在
            trace_file = tmp_path / "traces" / "sse-test-001.json"
            assert trace_file.exists()
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            assert data["trace_id"] == "sse-test-001"
            assert data["user_input"] == "test query"

    async def test_sse_error_still_traces(self, tmp_path):
        """即使出错，trace 也会被记录。"""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            events = [{"event": "on_chain_start", "name": "node", "data": {}}]

            collected = []
            async for event in simulate_sse_stream(events, stream_timeout=0.05, delay_per_event=0.1):
                collected.append(event)

            trace_file = tmp_path / "traces" / "sse-test-001.json"
            assert trace_file.exists()
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            assert data["processing_path"] == "timeout"
