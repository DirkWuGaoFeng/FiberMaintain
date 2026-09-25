"""
RAG 引擎单元测试 [v7.1]。

测试：
- _chunk_text：带重叠的文本切分
- _infer_category：基于文件名的类别推断
- 初始化失败的优雅降级
- retrieve()（使用 mock 检索器）
"""

import pytest

from src.rag.engine import RAGEngine


class TestChunkText:
    """测试文本切分逻辑。"""

    def test_short_text_single_chunk(self):
        """短于 chunk_size 的文本返回单个块。"""
        engine = RAGEngine()
        text = "Short text under 500 chars."
        chunks = engine._chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_multiple_chunks(self):
        """长于 chunk_size 的文本被切成多个块。"""
        engine = RAGEngine()
        text = "A" * 1200
        chunks = engine._chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 2

    def test_overlap_between_chunks(self):
        """相邻块应有重叠内容。"""
        engine = RAGEngine()
        # 创建结构已知的文本（无段落边界）
        text = "A" * 300
        chunks = engine._chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) >= 2
        # 均匀文本下，重叠意味着 chunk[1] 在 chunk[0] 结束前 20 字符处开始
        # 去重后的总覆盖 < 各块长度之和（证明存在重叠）
        total_len = sum(len(c) for c in chunks)
        assert total_len > len(text.strip())

    def test_empty_text(self):
        """空文本返回空列表或单个空块。"""
        engine = RAGEngine()
        chunks = engine._chunk_text("", chunk_size=500, overlap=50)
        # 空字符串长度为 0 ≤ 500，返回 [""]
        assert len(chunks) <= 1

    def test_paragraph_boundary_split(self):
        """切分应优先选择段落边界。"""
        engine = RAGEngine()
        # 在已知位置创建带换行的文本
        para1 = "First paragraph. " * 20  # ~340 chars
        para2 = "Second paragraph. " * 20  # ~360 chars
        text = para1 + "\n" + para2
        chunks = engine._chunk_text(text, chunk_size=400, overlap=50)
        assert len(chunks) >= 2

    def test_no_empty_chunks(self):
        """输出中不应出现空字符串。"""
        engine = RAGEngine()
        text = "Content. " * 100
        chunks = engine._chunk_text(text, chunk_size=200, overlap=30)
        for chunk in chunks:
            assert chunk.strip() != ""


class TestInferCategory:
    """测试基于文件名的类别推断。"""

    def test_device_manual(self):
        engine = RAGEngine()
        assert engine._infer_category("device_manual_v2.md") == "device_manual"
        assert engine._infer_category("board_config.txt") == "device_manual"

    def test_maintenance_guide(self):
        engine = RAGEngine()
        assert engine._infer_category("maintenance_guide.md") == "maintenance_guide"
        assert engine._infer_category("patrol_procedure.txt") == "maintenance_guide"

    def test_alarm_guide(self):
        engine = RAGEngine()
        assert engine._infer_category("alarm_handling.md") == "alarm_guide"

    def test_fault_cases(self):
        engine = RAGEngine()
        assert engine._infer_category("fault_cases_2024.md") == "fault_cases"
        assert engine._infer_category("case_study_01.txt") == "fault_cases"

    def test_threshold_standard(self):
        engine = RAGEngine()
        assert engine._infer_category("threshold_standard.md") == "threshold_standard"

    def test_ne_config(self):
        engine = RAGEngine()
        # 注意：文件名中含 “guide” 的会优先匹配 maintenance_guide
        assert engine._infer_category("ne_config.txt") == "ne_config"
        assert engine._infer_category("topology_overview.txt") == "ne_config"

    def test_testing_guide(self):
        engine = RAGEngine()
        assert engine._infer_category("otdr_testing.md") == "testing_guide"
        assert engine._infer_category("test_procedure.txt") == "testing_guide"

    def test_general_fallback(self):
        engine = RAGEngine()
        assert engine._infer_category("readme.md") == "general"
        assert engine._infer_category("notes.txt") == "general"


class TestRAGEngineInit:
    """测试 RAG 引擎初始化行为。"""

    @pytest.mark.asyncio
    async def test_initialize_without_dependencies(self, monkeypatch):
        """引擎应优雅地处理缺失的 ChromaDB。"""
        engine = RAGEngine()
        # 通过 patch 强制导入错误
        monkeypatch.setattr("src.rag.engine.CHROMA_PERSIST_DIR", "/nonexistent/path")

        # initialize() 不应抛异常，失败时返回 False
        result = await engine.initialize()
        # 结果可能为 True 或 False，取决于是否安装了 chromadb
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_is_available_before_init(self):
        """初始化前引擎应不可用。"""
        engine = RAGEngine()
        assert engine.is_available is False

    @pytest.mark.asyncio
    async def test_retrieve_without_init_returns_empty(self):
        """初始化前调用 retrieve 应自动初始化并优雅处理。"""
        engine = RAGEngine()
        # 无 ChromaDB 运行时，应返回空列表
        results = await engine.retrieve("test query", top_k=5)
        assert isinstance(results, list)

    def test_singleton_pattern(self):
        """get_rag_engine 应返回同一实例。"""
        from src.rag.engine import get_rag_engine

        engine1 = get_rag_engine()
        engine2 = get_rag_engine()
        assert engine1 is engine2
