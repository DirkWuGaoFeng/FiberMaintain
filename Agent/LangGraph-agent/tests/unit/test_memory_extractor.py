"""
测试：会话后记忆提取器 (MemoryExtractor) [v7.2 P0-1]。

覆盖书籍 Ch3 用户记忆系统核心机制：
- extract（LLM 结构化提取候选）
- verify（质量门禁：type/key/value/confidence 白名单）
- dedupe（(type,key) 去重取高置信度）
- store（偏好白名单 + 事件日志 + 脱敏）
- 完整流水线（异常安全：LLM 失败不抛出）
- API 端点（/api/v1/memory/extract）
"""

import os
import tempfile

import pytest

from src.memory.extractor import (
    MEMORY_TYPES,
    MemoryCandidate,
    MemoryExtractor,
)


@pytest.fixture
def temp_db():
    """临时数据库."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def store(temp_db):
    from src.memory.user_memory_store import UserMemoryStore

    return UserMemoryStore(db_path=temp_db)


@pytest.fixture
def extractor(store):
    return MemoryExtractor(store=store)


# =============================================================================
# 1. 质量门禁 verify
# =============================================================================


class TestVerify:
    def test_valid_candidate_passes(self, extractor):
        cand = MemoryCandidate(type="preference", key="default_format", value="table", confidence=0.9)
        assert extractor.verify_candidate(cand) is True

    def test_invalid_type_rejected(self, extractor):
        cand = MemoryCandidate(type="hack", key="x", value="y", confidence=0.9)
        assert extractor.verify_candidate(cand) is False

    def test_invalid_key_rejected(self, extractor):
        cand = MemoryCandidate(type="preference", key="not a valid key!!", value="y", confidence=0.9)
        assert extractor.verify_candidate(cand) is False

    def test_empty_value_rejected(self, extractor):
        cand = MemoryCandidate(type="fact", key="region", value="  ", confidence=0.9)
        assert extractor.verify_candidate(cand) is False

    def test_low_confidence_rejected(self, extractor):
        cand = MemoryCandidate(type="preference", key="language", value="zh", confidence=0.3)
        assert extractor.verify_candidate(cand) is False

    def test_batch_verify_filters(self, extractor):
        good = MemoryCandidate(type="fact", key="region", value="华东", confidence=0.9)
        bad = MemoryCandidate(type="preference", key="bad key", value="v", confidence=0.9)
        result = extractor.verify_candidates([good, bad])
        assert len(result) == 1
        assert result[0] is good


# =============================================================================
# 2. 去重
# =============================================================================


class TestDedupe:
    def test_dedupe_by_type_key_keeps_highest_confidence(self):
        low = MemoryCandidate(type="preference", key="language", value="zh", confidence=0.6)
        high = MemoryCandidate(type="preference", key="language", value="en", confidence=0.9)
        result = MemoryExtractor.dedupe_candidates([low, high])
        assert len(result) == 1
        assert result[0].value == "en"

    def test_dedupe_keeps_different_keys(self):
        a = MemoryCandidate(type="preference", key="language", value="zh", confidence=0.8)
        b = MemoryCandidate(type="fact", key="region", value="华东", confidence=0.8)
        result = MemoryExtractor.dedupe_candidates([a, b])
        assert len(result) == 2


# =============================================================================
# 3. 写入（白名单 + 事件日志）
# =============================================================================


class TestStore:
    def test_preference_only_whitelisted_keys(self, extractor, store):
        """偏好白名单外 key 丢弃（防脏键污染注入逻辑）。"""
        whitelisted = MemoryCandidate(type="preference", key="default_format", value="table", confidence=0.9)
        non_whitelisted = MemoryCandidate(type="preference", key="hacked_field", value="x", confidence=0.9)
        result = extractor.store_candidates("u-1", [whitelisted, non_whitelisted])
        assert result["preferences"] == 1
        loaded = store.load("u-1")
        assert loaded["preferences"].get("default_format") == "table"
        assert "hacked_field" not in loaded["preferences"]

    def test_fact_activity_written_to_events(self, extractor, store):
        fact = MemoryCandidate(type="fact", key="region", value="华东", confidence=0.9)
        act = MemoryCandidate(type="activity", key="recent_task", value="巡检光纤5", confidence=0.9)
        result = extractor.store_candidates("u-2", [fact, act])
        assert result["events"] == 2
        events = store.query_events("u-2", limit=10)
        assert len(events) == 2

    def test_store_sanitizes_value(self, extractor, store):
        """值写入前经 output_filter 脱敏（PII 保护）。"""
        cand = MemoryCandidate(type="fact", key="server", value="后端地址 192.168.1.1:8080", confidence=0.9)
        extractor.store_candidates("u-3", [cand])
        events = store.query_events("u-3", limit=10)
        assert "192.168.*.*" in events[0]["details"]["value"]


# =============================================================================
# 4. 完整流水线（mock LLM）
# =============================================================================


class TestPipeline:
    def _make_fake_llm(self, candidates: list[MemoryCandidate]):
        """构造返回固定候选的 fake LLM。"""
        from langchain_core.runnables import RunnableLambda

        from src.memory.extractor import MemoryCandidateList

        def _structured(*args, **kwargs):
            return RunnableLambda(lambda _: MemoryCandidateList(candidates=candidates))

        return type("FakeLLM", (), {"with_structured_output": _structured})()

    @pytest.mark.asyncio
    async def test_full_pipeline_extracts_and_stores(self, extractor, store, monkeypatch):
        llm = self._make_fake_llm(
            [
                MemoryCandidate(type="preference", key="language", value="中文", confidence=0.95),
                MemoryCandidate(type="fact", key="region", value="华东机房", confidence=0.9),
                # 低置信 + 非法 type：应被过滤
                MemoryCandidate(type="preference", key="guess", value="x", confidence=0.2),
                MemoryCandidate(type="hack", key="evil", value="x", confidence=0.99),
            ]
        )
        extractor._llm = llm
        # fake retriever：backfill 返回 0（避免依赖真实 embedding 服务）
        extractor._retriever = type(
            "FakeRetriever",
            (),
            {"backfill_embeddings": lambda self, *a, **k: _async_ret(0)},
        )()

        result = await extractor.extract_and_store(conversation="用户：请用表格输出", user_id="u-9")

        assert result["extracted"] == 4
        assert result["verified"] == 2  # 低置信 + 非法 type 被过滤
        # language 是白名单偏好 → preferences；region fact → events
        assert result["stored_prefs"] == 1
        assert result["stored_events"] == 1
        assert result["backfilled_embeddings"] == 0
        loaded = store.load("u-9")
        assert loaded["preferences"].get("language") == "中文"

    @pytest.mark.asyncio
    async def test_llm_failure_degrades_gracefully(self, extractor):
        """LLM 异常时返回空统计，不抛出（后台作业不阻塞调用方）。"""

        class _Broken:
            def with_structured_output(self, *args, **kwargs):
                raise RuntimeError("llm down")

        extractor._llm = _Broken()
        result = await extractor.extract_and_store("对话", "u-10")
        assert result == {
            "extracted": 0,
            "verified": 0,
            "stored_prefs": 0,
            "stored_events": 0,
            "backfilled_embeddings": 0,
        }


# =============================================================================
# 5. API 端点
# =============================================================================


class TestExtractEndpoint:
    @pytest.fixture
    def client(self):
        # 用独立 router 构造最小应用
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.frontend_api import router

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_extract_requires_user_id(self, client):
        resp = client.post(
            "/api/v1/memory/extract",
            json={"conversation": "hi", "user_id": ""},
        )
        assert resp.status_code == 400

    def test_extract_requires_conversation(self, client):
        resp = client.post(
            "/api/v1/memory/extract",
            json={"conversation": "", "user_id": "u-1"},
        )
        assert resp.status_code == 400

    def test_extract_endpoint_ok(self, client, monkeypatch):
        class _FakeExtractor:
            async def extract_and_store(self, **kwargs):
                return {
                    "extracted": 3,
                    "verified": 2,
                    "stored_prefs": 1,
                    "stored_events": 1,
                }

        monkeypatch.setattr("src.memory.extractor.get_memory_extractor", lambda: _FakeExtractor())
        resp = client.post(
            "/api/v1/memory/extract",
            json={"conversation": "用户：请用表格", "user_id": "u-1"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["stored_prefs"] == 1


async def _async_ret(value):
    """返回固定值的 async helper（供 fake retriever 使用）。"""
    return value


# =============================================================================
# 6. 常量契约
# =============================================================================


class TestConstants:
    def test_memory_types_cover_book_taxonomy(self):
        """三类别对应书籍 选择性/抽象化/结构化 的落地。"""
        assert set(MEMORY_TYPES) == {"preference", "fact", "activity"}
