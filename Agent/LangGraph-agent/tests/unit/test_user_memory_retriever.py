"""
测试：用户记忆语义检索器 (UserMemoryRetriever) [v7.2 P0-2]。

覆盖书籍 Ch3 双层记忆架构的"细节层"：
- save_event: 事件写入 + embedding 生成
- backfill_embeddings: 缺失 embedding 幂等回填
- query_semantic: 按查询文本语义召回相关历史事件
- query_hybrid: 语义优先 + 关键词兜底（embedding 不可用降级）
- extractor 集成: extract_and_store 后事件可被语义检索
- result_aggregator 接入: user_prefs 注入相关历史事件
"""

import os
import tempfile

import pytest

from src.memory.user_memory_retriever import UserMemoryRetriever


@pytest.fixture
def temp_db():
    """临时数据库."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def retriever(temp_db):
    return UserMemoryRetriever(db_path=temp_db)


def _fake_embedding_model(vectors: dict[str, list[float]]):
    """构造返回固定向量的 fake embedding 模型。"""

    class _Fake:
        async def aembed_query(self, text: str) -> list[float]:
            # 精确匹配返回指定向量；否则基于文本生成确定性向量
            if text in vectors:
                return vectors[text]
            # 确定性伪向量（保证语义相似文本向量相近）
            import hashlib

            h = int(hashlib.md5(text.encode()).hexdigest(), 16)
            return [((h >> (8 * i)) & 0xFF) / 255.0 for i in range(16)]

    return _Fake()


# =============================================================================
# 1. save_event：写入 + embedding
# =============================================================================


class TestSaveEvent:
    @pytest.mark.asyncio
    async def test_save_event_writes_and_embeds(self, retriever, monkeypatch):
        """事件写入 user_event_log 且生成 embedding。"""
        from src.memory.user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=retriever._db_path)

        monkeypatch.setattr(
            retriever,
            "_embed_text",
            lambda text: _async_vec([0.1] * 16),
        )
        ok = await retriever.save_event("u-1", "memory.fact", {"key": "region", "value": "华东"})
        assert ok is True

        # 事件可通过 store 查询到
        events = store.query_events("u-1", limit=10)
        assert len(events) == 1
        assert events[0]["event_type"] == "memory.fact"
        assert events[0]["details"]["value"] == "华东"

        # embedding 已写入
        import sqlite3

        conn = sqlite3.connect(retriever._db_path)
        row = conn.execute("SELECT embedding FROM user_event_log WHERE user_id='u-1'").fetchone()
        conn.close()
        assert row is not None and row[0] is not None


# =============================================================================
# 2. backfill_embeddings：幂等回填
# =============================================================================


class TestBackfill:
    @pytest.mark.asyncio
    async def test_backfill_only_missing(self, retriever, monkeypatch):
        """只回填 embedding IS NULL 的事件（幂等）。"""
        from src.memory.user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=retriever._db_path)
        store.log_event("u-1", "memory.fact", {"key": "a", "value": "x"})
        store.log_event("u-1", "memory.fact", {"key": "b", "value": "y"})

        # 先给第二条补上 embedding
        import sqlite3

        conn = sqlite3.connect(retriever._db_path)
        conn.execute(
            "UPDATE user_event_log SET embedding=? WHERE id=" "(SELECT MAX(id) FROM user_event_log)",
            (b"fake-blob",),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(retriever, "_embed_text", lambda t: _async_vec([0.5] * 16))
        filled = await retriever.backfill_embeddings("u-1")
        assert filled == 1  # 只有第一条被回填

        # 再跑一次：无缺失 → 0
        filled2 = await retriever.backfill_embeddings("u-1")
        assert filled2 == 0


# =============================================================================
# 3. query_semantic：语义召回
# =============================================================================


class TestQuerySemantic:
    @pytest.mark.asyncio
    async def test_semantic_retrieves_related_events(self, retriever, monkeypatch):
        """按查询文本召回语义相近的历史事件，并按相似度排序。"""
        from src.memory.user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=retriever._db_path)
        # 两个事件：一个与"机房"相关，一个与"报告"相关
        store.log_event(
            "u-1",
            "memory.fact",
            {"key": "region", "value": "华东机房", "source": "对话"},
        )
        store.log_event(
            "u-1",
            "memory.fact",
            {"key": "report_pref", "value": "用户偏好表格报告", "source": "对话"},
        )

        # 为两个事件写 embedding（用简单向量区分）
        monkeypatch.setattr(
            retriever,
            "_embed_text",
            _async_embed,
        )
        await retriever.backfill_embeddings("u-1")

        # 查询"用户负责哪个机房"
        results = await retriever.query_semantic("u-1", "用户负责哪个机房")
        assert len(results) >= 1
        # 语义上应优先召回机房事件
        assert results[0]["details"]["key"] == "region"

    @pytest.mark.asyncio
    async def test_semantic_falls_back_to_keyword(self, retriever, monkeypatch):
        """embedding 不可用时降级为关键词检索。"""
        from src.memory.user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=retriever._db_path)
        store.log_event("u-1", "memory.fact", {"key": "region", "value": "华东机房"})

        # embedding 模型不可用 → _embed_text 返回 None
        monkeypatch.setattr(retriever, "_embed_text", lambda t: _async_vec(None))
        results = await retriever.query_semantic("u-1", "华东")
        assert len(results) == 1
        assert results[0]["details"]["key"] == "region"


# =============================================================================
# 4. query_hybrid：语义优先 + 关键词补充
# =============================================================================


class TestQueryHybrid:
    @pytest.mark.asyncio
    async def test_hybrid_merges_semantic_and_keyword(self, retriever, monkeypatch):
        """语义结果不足时用关键词结果补充。"""
        from src.memory.user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=retriever._db_path)
        store.log_event("u-1", "memory.fact", {"key": "region", "value": "华东机房"})

        # embedding 不可用 → 语义返回空，靠关键词补充
        monkeypatch.setattr(retriever, "_embed_text", lambda t: _async_vec(None))
        results = await retriever.query_hybrid("u-1", "华东机房")
        assert len(results) == 1
        assert results[0]["details"]["key"] == "region"

    @pytest.mark.asyncio
    async def test_hybrid_empty_query_returns_empty(self, retriever):
        assert await retriever.query_hybrid("u-1", "") == []
        assert await retriever.query_hybrid("", "x") == []


# =============================================================================
# 5. extractor 集成：extract_and_store 后事件可被语义检索
# =============================================================================


class TestExtractorIntegration:
    @pytest.mark.asyncio
    async def test_extract_then_semantic_retrieve(self, temp_db, monkeypatch):
        """提取入库后，同一事件可被语义检索器召回。"""
        from langchain_core.runnables import RunnableLambda

        from src.memory.extractor import MemoryCandidate, MemoryCandidateList, MemoryExtractor
        from src.memory.user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=temp_db)

        class _FakeLLM:
            def with_structured_output(self, *args, **kwargs):
                return RunnableLambda(
                    lambda _: MemoryCandidateList(
                        candidates=[
                            MemoryCandidate(
                                type="fact",
                                key="region",
                                value="华东机房",
                                confidence=0.95,
                                source="对话",
                            ),
                        ]
                    )
                )

        extractor = MemoryExtractor(store=store, llm=_FakeLLM())
        monkeypatch.setattr(
            extractor._retriever,
            "_embed_text",
            lambda t: _async_vec([0.3] * 16),
        )

        result = await extractor.extract_and_store("用户负责华东机房", "u-9")
        assert result["stored_events"] == 1

        # 语义检索能召回该事件
        events = await extractor._retriever.query_hybrid("u-9", "负责的机房")
        assert len(events) >= 1
        assert events[0]["details"]["value"] == "华东机房"


# =============================================================================
# 6. result_aggregator 接入
# =============================================================================


class TestResultAggregatorIntegration:
    @pytest.mark.asyncio
    async def test_retrieve_user_events_injects_memory_events(self, monkeypatch):
        """result_aggregator 注入偏好时携带语义检索的历史事件。"""
        from src.nodes import result_aggregator as module

        class _FakeRetriever:
            async def query_hybrid(self, user_id, query_text, top_k=3):
                return [
                    {
                        "event_type": "memory.fact",
                        "details": {"key": "region", "value": "华东机房"},
                        "similarity": 0.88,
                    }
                ]

        monkeypatch.setattr(
            "src.memory.user_memory_retriever.get_user_memory_retriever",
            lambda: _FakeRetriever(),
        )
        # 偏好注入 mock（返回空偏好，聚焦事件检索）
        monkeypatch.setattr(
            "src.nodes.result_aggregator.get_user_memory_manager",
            lambda: type(
                "FakeManager",
                (),
                {"inject_preferences": lambda self, u, c: {}},
            )(),
        )

        state = {
            "user_id": "u-1",
            "user_input": "用户负责哪个机房",
            "final_output": "华东机房运行正常",
        }
        updates = await module.result_aggregator_node(state)
        assert updates["user_preferences"]["memory_events"][0]["details"]["value"] == "华东机房"

    @pytest.mark.asyncio
    async def test_retrieve_events_silent_on_failure(self, monkeypatch):
        """事件检索异常时不抛错，静默返回空（不阻塞主链路）。"""
        from src.nodes import result_aggregator as module

        class _Broken:
            async def query_hybrid(self, *args, **kwargs):
                raise RuntimeError("db down")

        monkeypatch.setattr(
            "src.memory.user_memory_retriever.get_user_memory_retriever",
            lambda: _Broken(),
        )
        monkeypatch.setattr(
            "src.nodes.result_aggregator.get_user_memory_manager",
            lambda: type(
                "FakeManager",
                (),
                {"inject_preferences": lambda self, u, c: {}},
            )(),
        )
        state = {"user_id": "u-1", "user_input": "x", "final_output": "y"}
        updates = await module.result_aggregator_node(state)
        assert "memory_events" not in updates.get("user_preferences", {})


# =============================================================================
# 辅助
# =============================================================================


async def _async_vec(vec):
    return vec


async def _async_embed(text: str) -> list[float]:
    """_embed_for 的 async 包装（供 monkeypatch _embed_text 使用）。"""
    return _embed_for(text)


def _embed_for(text: str) -> list[float]:
    """根据文本关键词生成可区分的确定性向量。"""
    # 含"机房/负责/华东" → 偏"机房"类
    if any(k in text for k in ("机房", "负责", "region", "华东")):
        return [0.9] * 16
    # 含"报告/表格" → 偏"报告"类
    if any(k in text for k in ("报告", "表格", "report")):
        return [0.1] * 16
    return [0.5] * 16
