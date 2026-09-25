"""
LangGraph-agent 测试的全局测试夹具（fixtures）。

提供：
- mock_backend: 在 FiberHttpClient 层面 mock C++ 后端
- mock_llm: Mock LLM 提供方（确定性响应）
- mock_rag: Mock RAG 引擎
- mock_memory_db: 独立的 SQLite 内存存储（tmp_path）
- mock_cache_db: 独立的 SQLite 缓存（tmp_path）
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# =============================================================================
# 全局单例重置（sse_starlette）
# =============================================================================


@pytest.fixture(autouse=True)
def _reset_sse_app_status():
    """重置 sse_starlette 的全局 AppStatus 单例。

    AppStatus.should_exit_event 是类级全局单例：第一个 SSE 测试创建它时会
    绑定到当前事件循环，而 pytest-asyncio 默认每个测试使用新的函数级事件循环，
    后续测试访问旧事件会抛 "bound to a different event loop"。
    每个测试前重置，强制 EventSourceResponse 重新绑定当前循环。
    """
    from sse_starlette.sse import AppStatus

    AppStatus.should_exit = False
    AppStatus.should_exit_event = None
    yield


# =============================================================================
# Mock 数据加载
# =============================================================================

MOCK_DATA_DIR = Path(__file__).parent / "mock_data"


def load_mock_data(filename: str) -> dict:
    """从 JSON 文件加载 mock 响应数据。"""
    filepath = MOCK_DATA_DIR / filename
    if filepath.exists():
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# =============================================================================
# C++ 后端 Mock Fixture
# =============================================================================


@pytest.fixture
def mock_backend(monkeypatch):
    """
    在 FiberHttpClient 层面 mock C++ 后端响应。

    用法：
        def test_something(mock_backend):
            mock_backend["/api/v1/fibers/1/spanloss"] = '{"spanloss": 3.2}'
            # ... 调用工具 ...
    """
    responses: dict[str, str] = {}

    # 预加载默认 mock 数据
    topology = load_mock_data("topology_responses.json")
    performance = load_mock_data("performance_responses.json")
    alarm = load_mock_data("alarm_responses.json")
    stats = load_mock_data("stats_responses.json")
    colored = load_mock_data("colored_responses.json")

    for data in [topology, performance, alarm, stats, colored]:
        for key, value in data.items():
            responses[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value

    def _normalize_path(path: str) -> str:
        """规范化路径：去掉数字段前导零。"""
        import re

        return re.sub(r"/0+(\d)", r"/\1", path)

    def _lookup(path: str) -> str | None:
        """按路径查找响应，带规范化回退。"""
        if path in responses:
            return responses[path]
        base_path = path.split("?")[0]
        if base_path in responses:
            return responses[base_path]
        # 尝试规范化路径（去掉前导零）
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

    # Patch 单例实例方法
    monkeypatch.setattr("src.tools._http_client.fiber_http_client.get", mock_get)
    monkeypatch.setattr("src.tools._http_client.fiber_http_client.post", mock_post)
    monkeypatch.setattr("src.tools._http_client.fiber_http_client.delete", mock_delete)

    # 同时 patch fast_path_executor 的直接导入
    monkeypatch.setattr("src.nodes.fast_path_executor.fiber_http_client.get", mock_get)
    monkeypatch.setattr("src.nodes.fast_path_executor.fiber_http_client.post", mock_post)

    return responses


# =============================================================================
# LLM 模拟夹具
# =============================================================================


@pytest.fixture
def mock_llm(monkeypatch):
    """
    Mock LLM 提供方以返回确定性响应。

    返回一个可供测试定制的字典：
        mock_llm["intent"] = '{"intent": "single_query", ...}'
        mock_llm["narrator"] = "光纤1衰耗为6.5dB..."
    """
    llm_responses = {
        "intent": json.dumps(
            {
                "intent": "single_query",
                "fiber_ids": ["1"],
                "board_ids": [],
                "port_ids": [],
                "ne_id": None,
                "color": None,
                "time_range": None,
                "confidence": 0.95,
            }
        ),
        "analysis": json.dumps(
            {
                "conclusion": "光纤衰耗在正常范围内",
                "severity": "NORMAL",
                "evidence": ["spanloss=3.2dB < 5.0dB"],
                "confidence": 0.9,
                "need_more_data": False,
                "additional_query": None,
            }
        ),
        "narrator": "光纤1的衰耗为3.2dB，低于阈值5.0dB，状态正常。",
        "knowledge": "OTDR（光时域反射仪）是一种用于光纤测试的仪器。",
        "report": "# 光纤维护报告\n\n## 概要\n所有光纤状态正常。",
        "report_eval": json.dumps({"passed": True, "refinement_count": 0}),
        "data_collector": json.dumps(
            {
                "collected": [
                    {"tool": "fiber_spanloss_query", "params": {"fiber_id": 1}, "result_summary": "spanloss=3.2dB"}
                ],
                "errors": [],
            }
        ),
    }

    class MockChatOllama:
        """返回预定义响应的 Mock ChatOllama。"""

        def __init__(self, *args, **kwargs):
            self.model = kwargs.get("model", "mock-model")
            self.temperature = kwargs.get("temperature", 0.1)

        async def ainvoke(self, messages, config=None, **kwargs):
            from langchain_core.messages import AIMessage

            # 根据上下文确定响应
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
            """返回一个产生结构化输出的 mock。"""
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

    # Patch 所有 LLM 提供方函数
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
# RAG 引擎 Mock Fixture
# =============================================================================


@pytest.fixture
def mock_rag(monkeypatch):
    """Mock RAG 引擎以返回预定义的知识块。"""
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
# 内存存储 Fixture（独立 DB）
# =============================================================================


@pytest.fixture
def memory_db_path(tmp_path):
    """为内存存储测试提供独立的 SQLite DB 路径。"""
    return str(tmp_path / "test_memory.db")


# =============================================================================
# 缓存 Fixture（独立 DB）
# =============================================================================


@pytest.fixture
def cache_db_path(tmp_path):
    """为缓存测试提供独立的 SQLite DB 路径。"""
    return str(tmp_path / "test_cache.db")


# =============================================================================
# 环境隔离
# =============================================================================


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch, tmp_path):
    """确保测试不会污染真实数据目录。"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMORY_DB", str(tmp_path / "memory.db"))
    monkeypatch.setenv("LOCAL_CACHE_DB", str(tmp_path / "cache.db"))
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "checkpoints.db"))
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "audit.jsonl"))
    monkeypatch.setenv("EXPORT_DIR", str(tmp_path / "exports"))
