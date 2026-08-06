"""
Global test fixtures for LangGraph-agent tests.

Provides:
- mock_backend: Mock C++ backend at FiberHttpClient level
- mock_llm: Mock LLM provider (deterministic responses)
- mock_rag: Mock RAG engine
- mock_memory_db: Isolated SQLite memory store (tmp_path)
- mock_cache_db: Isolated SQLite cache (tmp_path)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# Mock Data Loading
# =============================================================================

MOCK_DATA_DIR = Path(__file__).parent / "mock_data"


def load_mock_data(filename: str) -> dict:
    """Load mock response data from JSON file."""
    filepath = MOCK_DATA_DIR / filename
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# =============================================================================
# C++ Backend Mock Fixture
# =============================================================================


@pytest.fixture
def mock_backend(monkeypatch):
    """
    Mock C++ backend responses at FiberHttpClient level.

    Usage:
        def test_something(mock_backend):
            mock_backend["/api/v1/fibers/1/spanloss"] = '{"spanloss": 3.2}'
            # ... call tool ...
    """
    responses: dict[str, str] = {}

    # Pre-load default mock data
    topology = load_mock_data("topology_responses.json")
    performance = load_mock_data("performance_responses.json")
    alarm = load_mock_data("alarm_responses.json")
    stats = load_mock_data("stats_responses.json")
    colored = load_mock_data("colored_responses.json")

    for data in [topology, performance, alarm, stats, colored]:
        for key, value in data.items():
            responses[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value

    def _normalize_path(path: str) -> str:
        """Normalize path: strip leading zeros from numeric segments."""
        import re
        return re.sub(r'/0+(\d)', r'/\1', path)

    def _lookup(path: str) -> str | None:
        """Lookup response by path with normalization fallback."""
        if path in responses:
            return responses[path]
        base_path = path.split("?")[0]
        if base_path in responses:
            return responses[base_path]
        # Try normalized path (strip leading zeros)
        normalized = _normalize_path(base_path)
        if normalized in responses:
            return responses[normalized]
        return None

    async def mock_get(path: str, timeout: float = 2.0, params=None) -> str:
        result = _lookup(path)
        if result is not None:
            return result
        return json.dumps({"error": True, "message": f"No mock for GET {path}"}, ensure_ascii=False)

    async def mock_post(path: str, timeout: float = 5.0, **kwargs) -> str:
        result = _lookup(path)
        if result is not None:
            return result
        return json.dumps({"error": True, "message": f"No mock for POST {path}"}, ensure_ascii=False)

    async def mock_delete(path: str, timeout: float = 3.0, params=None) -> str:
        result = _lookup(path)
        if result is not None:
            return result
        return json.dumps({"error": True, "message": f"No mock for DELETE {path}"}, ensure_ascii=False)

    # Patch the singleton instance methods
    monkeypatch.setattr("src.tools._http_client.fiber_http_client.get", mock_get)
    monkeypatch.setattr("src.tools._http_client.fiber_http_client.post", mock_post)
    monkeypatch.setattr("src.tools._http_client.fiber_http_client.delete", mock_delete)

    # Also patch fast_path_executor's direct import
    monkeypatch.setattr("src.nodes.fast_path_executor.fiber_http_client.get", mock_get)
    monkeypatch.setattr("src.nodes.fast_path_executor.fiber_http_client.post", mock_post)

    return responses


# =============================================================================
# LLM Mock Fixture
# =============================================================================


@pytest.fixture
def mock_llm(monkeypatch):
    """
    Mock LLM provider to return deterministic responses.

    Returns a dict that tests can customize:
        mock_llm["intent"] = '{"intent": "single_query", ...}'
        mock_llm["narrator"] = "光纤1衰耗为6.5dB..."
    """
    llm_responses = {
        "intent": json.dumps({
            "intent": "single_query",
            "fiber_ids": ["1"],
            "board_ids": [],
            "port_ids": [],
            "ne_id": None,
            "color": None,
            "time_range": None,
            "confidence": 0.95,
        }),
        "analysis": json.dumps({
            "conclusion": "光纤衰耗在正常范围内",
            "severity": "NORMAL",
            "evidence": ["spanloss=3.2dB < 5.0dB"],
            "confidence": 0.9,
            "need_more_data": False,
            "additional_query": None,
        }),
        "narrator": "光纤1的衰耗为3.2dB，低于阈值5.0dB，状态正常。",
        "knowledge": "OTDR（光时域反射仪）是一种用于光纤测试的仪器。",
        "report": "# 光纤维护报告\n\n## 概要\n所有光纤状态正常。",
        "report_eval": json.dumps({"passed": True, "refinement_count": 0}),
        "data_collector": json.dumps({
            "collected": [{"tool": "fiber_spanloss_query", "params": {"fiber_id": 1}, "result_summary": "spanloss=3.2dB"}],
            "errors": [],
        }),
    }

    class MockChatOllama:
        """Mock ChatOllama that returns predetermined responses."""

        def __init__(self, *args, **kwargs):
            self.model = kwargs.get("model", "mock-model")
            self.temperature = kwargs.get("temperature", 0.1)

        async def ainvoke(self, messages, config=None, **kwargs):
            from langchain_core.messages import AIMessage
            # Determine response based on context
            content = str(messages) if isinstance(messages, list) else str(messages)
            if "意图" in content or "intent" in content.lower():
                return AIMessage(content=llm_responses["intent"])
            elif "分析" in content or "analysis" in content.lower():
                return AIMessage(content=llm_responses["analysis"])
            elif "叙述" in content or "narrat" in content.lower():
                return AIMessage(content=llm_responses["narrator"])
            elif "报告" in content or "report" in content.lower():
                return AIMessage(content=llm_responses["report"])
            else:
                return AIMessage(content=llm_responses["data_collector"])

        def with_structured_output(self, schema, **kwargs):
            """Return a mock that produces structured output."""
            mock = AsyncMock()

            async def _structured_invoke(messages, **kw):
                content = str(messages)
                if "意图" in content or "intent" in content.lower():
                    return json.loads(llm_responses["intent"])
                elif "分析" in content or "analysis" in content.lower():
                    return json.loads(llm_responses["analysis"])
                return json.loads(llm_responses["analysis"])

            mock.ainvoke = _structured_invoke
            return mock

        def with_fallbacks(self, fallbacks, **kwargs):
            return self

        def bind_tools(self, tools, **kwargs):
            return self

    # Patch all LLM provider functions
    mock_instance = MockChatOllama()
    monkeypatch.setattr("src.llm.provider.get_primary_llm", lambda *a, **kw: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_secondary_llm", lambda *a, **kw: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_tertiary_llm", lambda *a, **kw: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_intent_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_analysis_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_narrator_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_knowledge_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_report_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_report_eval_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_data_collector_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_batch_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_query_rewriter_llm", lambda: mock_instance)
    monkeypatch.setattr("src.llm.provider.get_llm_with_fallback", lambda *a, **kw: mock_instance)

    return llm_responses


# =============================================================================
# RAG Engine Mock Fixture
# =============================================================================


@pytest.fixture
def mock_rag(monkeypatch):
    """Mock RAG engine to return predetermined knowledge chunks."""
    rag_results = [
        {
            "content": "OTDR（光时域反射仪）通过向光纤发射光脉冲并检测反射信号来测量光纤特性。",
            "metadata": {"source": "testing_guide.md", "category": "testing_guide", "chunk_index": 0},
            "score": 0.85,
        },
        {
            "content": "光纤衰耗超过5.0dB时应标记为黄色预警，超过8.0dB标记为红色告警。",
            "metadata": {"source": "threshold_standard.md", "category": "threshold_standard", "chunk_index": 2},
            "score": 0.72,
        },
    ]

    mock_engine = AsyncMock()
    mock_engine.is_available = True
    mock_engine.retrieve = AsyncMock(return_value=rag_results)
    mock_engine.initialize = AsyncMock(return_value=True)

    monkeypatch.setattr("src.rag.engine.get_rag_engine", lambda: mock_engine)

    return mock_engine


# =============================================================================
# Memory Store Fixture (isolated DB)
# =============================================================================


@pytest.fixture
def memory_db_path(tmp_path):
    """Provide an isolated SQLite DB path for memory store tests."""
    return str(tmp_path / "test_memory.db")


# =============================================================================
# Cache Fixture (isolated DB)
# =============================================================================


@pytest.fixture
def cache_db_path(tmp_path):
    """Provide an isolated SQLite DB path for cache tests."""
    return str(tmp_path / "test_cache.db")


# =============================================================================
# Environment Isolation
# =============================================================================


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """Ensure tests don't pollute real data directories."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LOCAL_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
