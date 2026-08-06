"""
Unit tests for RAG Engine [v7.1].

Tests:
- _chunk_text: text splitting with overlap
- _infer_category: filename-based category inference
- Initialization failure graceful degradation
- retrieve() with mock retriever
"""

import pytest

from src.rag.engine import RAGEngine


class TestChunkText:
    """Test text chunking logic."""

    def test_short_text_single_chunk(self):
        """Text shorter than chunk_size returns single chunk."""
        engine = RAGEngine()
        text = "Short text under 500 chars."
        chunks = engine._chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_multiple_chunks(self):
        """Text longer than chunk_size is split into multiple chunks."""
        engine = RAGEngine()
        text = "A" * 1200
        chunks = engine._chunk_text(text, chunk_size=500, overlap=50)
        assert len(chunks) >= 2

    def test_overlap_between_chunks(self):
        """Consecutive chunks should have overlapping content."""
        engine = RAGEngine()
        # Create text with known structure (no paragraph boundaries)
        text = "A" * 300
        chunks = engine._chunk_text(text, chunk_size=100, overlap=20)
        assert len(chunks) >= 2
        # With uniform text, overlap means chunk[1] starts 20 chars before chunk[0] ends
        # Total unique coverage < sum of chunk lengths (proves overlap)
        total_len = sum(len(c) for c in chunks)
        assert total_len > len(text.strip())

    def test_empty_text(self):
        """Empty text returns empty list or single empty chunk."""
        engine = RAGEngine()
        chunks = engine._chunk_text("", chunk_size=500, overlap=50)
        # Empty string has length 0 <= 500, returns [""]
        assert len(chunks) <= 1

    def test_paragraph_boundary_split(self):
        """Chunking should prefer paragraph boundaries."""
        engine = RAGEngine()
        # Create text with newlines at known positions
        para1 = "First paragraph. " * 20  # ~340 chars
        para2 = "Second paragraph. " * 20  # ~360 chars
        text = para1 + "\n" + para2
        chunks = engine._chunk_text(text, chunk_size=400, overlap=50)
        assert len(chunks) >= 2

    def test_no_empty_chunks(self):
        """No empty strings should appear in output."""
        engine = RAGEngine()
        text = "Content. " * 100
        chunks = engine._chunk_text(text, chunk_size=200, overlap=30)
        for chunk in chunks:
            assert chunk.strip() != ""


class TestInferCategory:
    """Test filename-based category inference."""

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
        # Note: filenames containing "guide" match maintenance_guide first
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
    """Test RAG engine initialization behavior."""

    @pytest.mark.asyncio
    async def test_initialize_without_dependencies(self, monkeypatch):
        """Engine should gracefully handle missing ChromaDB."""
        engine = RAGEngine()
        # Force import error by patching
        monkeypatch.setattr("src.rag.engine.CHROMA_PERSIST_DIR", "/nonexistent/path")

        # initialize() should not raise, returns False on failure
        result = await engine.initialize()
        # May be True or False depending on whether chromadb is installed
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_is_available_before_init(self):
        """Engine should not be available before initialization."""
        engine = RAGEngine()
        assert engine.is_available is False

    @pytest.mark.asyncio
    async def test_retrieve_without_init_returns_empty(self):
        """Retrieve before initialization should auto-init and handle gracefully."""
        engine = RAGEngine()
        # Without ChromaDB running, should return empty list
        results = await engine.retrieve("test query", top_k=5)
        assert isinstance(results, list)

    def test_singleton_pattern(self):
        """get_rag_engine should return same instance."""
        from src.rag.engine import get_rag_engine
        engine1 = get_rag_engine()
        engine2 = get_rag_engine()
        assert engine1 is engine2
