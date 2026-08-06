"""
Tests for SSE timeout, heartbeat, and tracer integration [v7.2].

Tests:
- Heartbeat emission during long-running requests
- Timeout error event with trace_id
- Normal completion with final_output event
- Tracer file generation after request completion

Uses mock graph to simulate various SSE scenarios without real LLM/backend.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Helper: Simulate SSE event generator logic (extracted from server.py)
# =============================================================================


async def simulate_sse_stream(
    events: list[dict],
    stream_timeout: float = 120.0,
    heartbeat_interval: float = 5.0,
    delay_per_event: float = 0.0,
):
    """
    Simulate the SSE event generator logic from server.py.

    Yields SSE event dicts (same format as server.py event_generator).
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

                # Capture final_output
                if (event.get("event") == "on_chain_end"
                        and event.get("name") in ("result_aggregator", "fast_path_executor")):
                    output = event.get("data", {}).get("output", {})
                    if isinstance(output, dict) and output.get("final_output"):
                        final_output = output["final_output"]
                    if isinstance(output, dict) and output.get("processing_path"):
                        processing_path = output["processing_path"]

                # Heartbeat
                if now - last_heartbeat >= heartbeat_interval:
                    elapsed_ms = int((now - start_time) * 1000)
                    heartbeat = {
                        "event": "heartbeat",
                        "data": {"elapsed_ms": elapsed_ms, "status": "processing"},
                    }
                    yield heartbeat
                    last_heartbeat = now

                yield event

        # Final output event
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
    """Test heartbeat emission during long-running requests."""

    async def test_sse_heartbeat_emission(self):
        """Long-running request emits heartbeat events."""
        # Simulate events with delay to trigger heartbeat
        events = [
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {}}},
            {"event": "on_chain_start", "name": "intent_classifier", "data": {}},
            {"event": "on_chain_end", "name": "intent_classifier", "data": {"output": {}}},
        ]

        collected = []
        # Use very short heartbeat interval to trigger in test
        async for event in simulate_sse_stream(
            events, heartbeat_interval=0.01, delay_per_event=0.02
        ):
            collected.append(event)

        # Should have heartbeat events mixed in
        heartbeats = [e for e in collected if e.get("event") == "heartbeat"]
        # With 4 events * 0.02s delay and 0.01s heartbeat interval, expect at least 1
        assert len(heartbeats) >= 1
        # Heartbeat has correct structure
        hb = heartbeats[0]
        assert "elapsed_ms" in hb["data"]
        assert hb["data"]["status"] == "processing"

    async def test_no_heartbeat_for_fast_requests(self):
        """Fast requests don't emit heartbeat."""
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
    """Test timeout error event."""

    async def test_sse_timeout_error_event(self):
        """Timeout produces error event with trace_id."""
        # Create an event list that will "hang" (simulate with long delay)
        events = [{"event": "on_chain_start", "name": "data_collector", "data": {}}]

        collected = []
        # Very short timeout to trigger in test
        async for event in simulate_sse_stream(
            events, stream_timeout=0.05, delay_per_event=0.1
        ):
            collected.append(event)

        # Should have timeout error event
        errors = [e for e in collected if e.get("event") == "error"]
        assert len(errors) == 1
        err = errors[0]
        assert err["data"]["code"] == "TIMEOUT"
        assert "trace_id" in err["data"]
        assert err["data"]["trace_id"] == "sse-test-001"
        assert err["data"]["elapsed_ms"] > 0

    async def test_sse_timeout_message_format(self):
        """Timeout message includes timeout duration."""
        events = [{"event": "on_chain_start", "name": "analysis_expert", "data": {}}]

        collected = []
        async for event in simulate_sse_stream(
            events, stream_timeout=0.05, delay_per_event=0.1
        ):
            collected.append(event)

        errors = [e for e in collected if e.get("event") == "error"]
        assert len(errors) == 1
        assert "0.05s" in errors[0]["data"]["message"]


class TestSSENormalCompletion:
    """Test normal completion with final_output."""

    async def test_sse_normal_completion(self):
        """Normal request emits final_output event."""
        events = [
            {"event": "on_chain_start", "name": "rule_engine", "data": {}},
            {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {"rule_match": {"intent": "spanloss_query"}}}},
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

        # Should have final_output event
        finals = [e for e in collected if e.get("event") == "final_output"]
        assert len(finals) == 1
        assert finals[0]["data"]["output"] == "光纤1衰耗3.2dB正常"

    async def test_sse_no_final_output_without_result(self):
        """No final_output event if no result_aggregator/fast_path output."""
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
    """Test tracer integration with SSE stream."""

    async def test_sse_tracer_integration(self, tmp_path):
        """Request completion generates trace file."""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            events = [
                {"event": "on_chain_start", "name": "rule_engine", "data": {}},
                {"event": "on_chain_end", "name": "rule_engine", "data": {"output": {}}},
            ]

            collected = []
            async for event in simulate_sse_stream(events):
                collected.append(event)

            # Trace file should exist
            trace_file = tmp_path / "traces" / "sse-test-001.json"
            assert trace_file.exists()
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            assert data["trace_id"] == "sse-test-001"
            assert data["user_input"] == "test query"

    async def test_sse_error_still_traces(self, tmp_path):
        """Even on error, trace is recorded."""
        with patch("src.observability.request_tracer.TRACES_DIR", tmp_path / "traces"):
            events = [{"event": "on_chain_start", "name": "node", "data": {}}]

            collected = []
            async for event in simulate_sse_stream(
                events, stream_timeout=0.05, delay_per_event=0.1
            ):
                collected.append(event)

            trace_file = tmp_path / "traces" / "sse-test-001.json"
            assert trace_file.exists()
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            assert data["processing_path"] == "timeout"
