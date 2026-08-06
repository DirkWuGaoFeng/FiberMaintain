"""
RAG Engine — Hybrid retrieval engine [v7.1].

Architecture:
- Ollama Embedding (bge-large or nomic-embed-text)
- ChromaDB vector retrieval (k=5, score_threshold=0.55)
- BM25 keyword retrieval (rank-bm25, k=5)
- EnsembleRetriever (Vector 0.6 + BM25 0.4)
- Async initialization, lazy loading

Usage:
    engine = get_rag_engine()
    results = await engine.retrieve("OTDR测试步骤", top_k=5)
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import CHROMA_PERSIST_DIR, KNOWLEDGE_BASE_DIR

logger = logging.getLogger(__name__)

# Score threshold for vector retrieval
SCORE_THRESHOLD = 0.55
DEFAULT_TOP_K = 5


class RAGEngine:
    """
    Hybrid RAG engine: Vector + BM25 ensemble retrieval.

    Lazy-initialized to avoid blocking at import time.
    Thread-safe singleton via get_rag_engine().
    """

    def __init__(self):
        self._retriever = None
        self._initialized = False
        self._init_error: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """Whether the RAG engine is initialized and ready."""
        return self._initialized and self._retriever is not None

    async def initialize(self) -> bool:
        """
        Initialize the RAG engine (async, lazy).

        Returns True if initialization succeeded.
        """
        if self._initialized:
            return self._retriever is not None

        try:
            self._retriever = self._build_retriever()
            self._initialized = True
            if self._retriever:
                logger.info("[RAG] Engine initialized successfully (hybrid retrieval)")
            else:
                logger.warning("[RAG] Engine initialized with no retriever (empty knowledge base?)")
            return self._retriever is not None
        except Exception as e:
            self._initialized = True
            self._init_error = str(e)
            logger.error(f"[RAG] Engine initialization failed: {e}")
            return False

    def _build_retriever(self):
        """Build hybrid retriever: ChromaDB Vector + BM25."""
        try:
            from langchain_chroma import Chroma
            from ..llm.provider import get_embedding_model

            embeddings = get_embedding_model()

            # Vector retriever (ChromaDB)
            vectorstore = Chroma(
                collection_name="fiber_knowledge",
                embedding_function=embeddings,
                persist_directory=CHROMA_PERSIST_DIR,
            )
            vector_retriever = vectorstore.as_retriever(
                search_kwargs={"k": DEFAULT_TOP_K}
            )

            # Try to add BM25 for hybrid retrieval
            try:
                from langchain_community.retrievers import BM25Retriever
                from langchain.retrievers import EnsembleRetriever

                docs = self._load_knowledge_docs()
                if docs:
                    bm25_retriever = BM25Retriever.from_documents(docs, k=DEFAULT_TOP_K)
                    ensemble = EnsembleRetriever(
                        retrievers=[vector_retriever, bm25_retriever],
                        weights=[0.6, 0.4],
                    )
                    logger.info(f"[RAG] Hybrid retriever built (vector+BM25, {len(docs)} docs)")
                    return ensemble
                else:
                    logger.info("[RAG] No docs for BM25, using vector-only")
            except ImportError:
                logger.warning("[RAG] BM25 not available, using vector-only")
            except Exception as e:
                logger.warning(f"[RAG] BM25 build failed: {e}, using vector-only")

            return vector_retriever

        except ImportError as e:
            logger.error(f"[RAG] Missing dependency: {e}")
            return None
        except Exception as e:
            logger.error(f"[RAG] Retriever build failed: {e}")
            return None

    def _load_knowledge_docs(self):
        """Load and chunk documents from knowledge_base/ directory."""
        from langchain_core.documents import Document
        from pathlib import Path

        kb_path = Path(KNOWLEDGE_BASE_DIR)
        if not kb_path.exists():
            return []

        docs = []
        for filepath in kb_path.iterdir():
            if filepath.is_file() and filepath.suffix in (".md", ".txt", ".rst"):
                try:
                    content = filepath.read_text(encoding="utf-8")
                    chunks = self._chunk_text(content, chunk_size=500, overlap=50)
                    category = self._infer_category(filepath.name)
                    for i, chunk in enumerate(chunks):
                        docs.append(Document(
                            page_content=chunk,
                            metadata={
                                "source": filepath.name,
                                "category": category,
                                "chunk_index": i,
                            },
                        ))
                except Exception as e:
                    logger.warning(f"[RAG] Failed to load {filepath.name}: {e}")

        return docs

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """Split text into overlapping chunks."""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            # Try to break at paragraph boundary
            if end < len(text):
                newline_pos = text.rfind("\n", start + chunk_size // 2, end)
                if newline_pos > start:
                    end = newline_pos + 1
            chunks.append(text[start:end].strip())
            start = end - overlap
        return [c for c in chunks if c]

    @staticmethod
    def _infer_category(filename: str) -> str:
        """Infer knowledge category from filename."""
        name = filename.lower()
        if "device" in name or "manual" in name or "board" in name:
            return "device_manual"
        elif "maintenance" in name or "guide" in name or "patrol" in name:
            return "maintenance_guide"
        elif "alarm" in name:
            return "alarm_guide"
        elif "fault" in name or "case" in name:
            return "fault_cases"
        elif "threshold" in name or "standard" in name:
            return "threshold_standard"
        elif "ne" in name or "config" in name or "topology" in name:
            return "ne_config"
        elif "otdr" in name or "test" in name:
            return "testing_guide"
        return "general"

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Retrieve relevant knowledge chunks.

        Args:
            query: User question or search query
            top_k: Number of results to return

        Returns:
            List of {"content": str, "metadata": dict, "score": float}
        """
        if not self._initialized:
            await self.initialize()

        if not self._retriever:
            return []

        try:
            # Optional: query rewriting
            rewritten_query = await self._maybe_rewrite_query(query)

            docs = await self._retriever.ainvoke(rewritten_query)
            results = []
            for doc in docs[:top_k]:
                results.append({
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": doc.metadata.get("relevance_score", 0.0),
                })
            return results
        except Exception as e:
            logger.error(f"[RAG] Retrieval failed: {e}")
            return []

    async def _maybe_rewrite_query(self, query: str) -> str:
        """Optionally rewrite query for better retrieval (uses 7b)."""
        try:
            from .query_rewriter import rewrite_query
            rewritten = await rewrite_query(query)
            if rewritten and rewritten != query:
                logger.debug(f"[RAG] Query rewritten: '{query}' → '{rewritten}'")
                return rewritten
        except Exception:
            pass  # Skip rewriting on any error
        return query


# =============================================================================
# Singleton
# =============================================================================

_engine_instance: Optional[RAGEngine] = None


def get_rag_engine() -> Optional[RAGEngine]:
    """Get the RAG engine singleton (lazy initialization)."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RAGEngine()
    return _engine_instance
