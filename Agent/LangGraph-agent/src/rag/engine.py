"""
RAG 引擎 — 混合检索引擎 [v7.1]。

架构：
- Ollama Embedding（bge-large 或 nomic-embed-text）
- ChromaDB 向量检索（k=5, score_threshold=0.55）
- BM25 关键词检索（rank-bm25, k=5）
- EnsembleRetriever（向量 0.6 + BM25 0.4）
- 异步初始化、懒加载

用法：
    engine = get_rag_engine()
    results = await engine.retrieve("OTDR测试步骤", top_k=5)
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import CHROMA_PERSIST_DIR, KNOWLEDGE_BASE_DIR

logger = logging.getLogger(__name__)

# 向量检索的分数阈值
SCORE_THRESHOLD = 0.55
DEFAULT_TOP_K = 5


class RAGEngine:
    """
    Hybrid RAG engine: Vector + BM25 ensemble retrieval.

    Lazy-initialized to avoid blocking at import time.
    Thread-safe singleton via get_rag_engine().
    """

    def __init__(self):
        self._retriever = None  # 单一 retriever（向量 or BM25-only 降级）
        self._vector_retriever = None  # 向量检索器
        self._bm25_retriever = None  # BM25 检索器
        self._hybrid = False  # 是否启用混合检索
        self._initialized = False
        self._init_error: Optional[str] = None

    @property
    def is_available(self) -> bool:
        """RAG 引擎是否已初始化并可用。"""
        return self._initialized and self._retriever is not None

    async def initialize(self) -> bool:
        """
        初始化 RAG 引擎（异步、懒加载）。

        初始化成功时返回 True。
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
        """构建混合检索器：ChromaDB 向量 + BM25。"""
        try:
            from langchain_chroma import Chroma

            from ..llm.provider import get_embedding_model

            embeddings = get_embedding_model()

            # 向量检索器（ChromaDB）
            vectorstore = Chroma(
                collection_name="fiber_knowledge",
                embedding_function=embeddings,
                persist_directory=CHROMA_PERSIST_DIR,
            )
            vector_retriever = vectorstore.as_retriever(search_kwargs={"k": DEFAULT_TOP_K})

            # 尝试添加 BM25 实现混合检索
            try:
                from langchain_community.retrievers import BM25Retriever

                docs = self._load_knowledge_docs()
                if docs:
                    bm25_retriever = BM25Retriever.from_documents(docs, k=DEFAULT_TOP_K)
                    self._vector_retriever = vector_retriever
                    self._bm25_retriever = bm25_retriever
                    self._hybrid = True
                    logger.info(f"[RAG] Hybrid retriever built (vector+BM25, {len(docs)} docs)")
                    return vector_retriever  # 返回非 None 标记初始化成功
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
        """从 knowledge_base/ 目录加载并分块文档。"""
        from pathlib import Path

        from langchain_core.documents import Document

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
                        docs.append(
                            Document(
                                page_content=chunk,
                                metadata={
                                    "source": filepath.name,
                                    "category": category,
                                    "chunk_index": i,
                                },
                            )
                        )
                except Exception as e:
                    logger.warning(f"[RAG] Failed to load {filepath.name}: {e}")

        return docs

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        """将文本切分为重叠的分块。"""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            # 尝试在段落边界处断开
            if end < len(text):
                newline_pos = text.rfind("\n", start + chunk_size // 2, end)
                if newline_pos > start:
                    end = newline_pos + 1
            chunks.append(text[start:end].strip())
            start = end - overlap
        return [c for c in chunks if c]

    @staticmethod
    def _infer_category(filename: str) -> str:
        """根据文件名推断知识类别。"""
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
        检索相关的知识片段。

        Args:
            query: 用户问题或搜索查询
            top_k: 返回的结果数量

        Returns:
            形如 {"content": str, "metadata": dict, "score": float} 的列表
        """
        if not self._initialized:
            await self.initialize()

        if not self._retriever:
            return []

        try:
            # 可选：查询改写
            rewritten_query = await self._maybe_rewrite_query(query)

            if self._hybrid and self._vector_retriever and self._bm25_retriever:
                # 加权混合检索：vector 0.6 + BM25 0.4
                vec_docs = await self._vector_retriever.ainvoke(rewritten_query)
                bm25_docs = await self._bm25_retriever.ainvoke(rewritten_query)
                docs = self._merge_results(vec_docs, bm25_docs, w_vector=0.6, w_bm25=0.4, top_k=top_k)
            elif self._retriever:
                docs = await self._retriever.ainvoke(rewritten_query)
                docs = docs[:top_k]
            else:
                return []

            results = []
            for doc in docs:
                results.append(
                    {
                        "content": doc.page_content,
                        "metadata": doc.metadata,
                        "score": doc.metadata.get("relevance_score", 0.0),
                    }
                )
            return results
        except Exception as e:
            logger.error(f"[RAG] Retrieval failed: {e}")
            return []

    @staticmethod
    def _merge_results(vec_docs, bm25_docs, w_vector=0.6, w_bm25=0.4, top_k=5):
        """RRF (Reciprocal Rank Fusion) 合并向量与 BM25 结果。"""
        from langchain_core.documents import Document

        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        # 向量结果：按排名赋予分数
        for rank, doc in enumerate(vec_docs):
            key = doc.metadata.get("source", "") + "|" + doc.page_content[:80]
            scores[key] = scores.get(key, 0.0) + w_vector * (1.0 / (rank + 1))
            doc_map[key] = doc

        # BM25 结果：按排名赋予分数
        for rank, doc in enumerate(bm25_docs):
            key = doc.metadata.get("source", "") + "|" + doc.page_content[:80]
            scores[key] = scores.get(key, 0.0) + w_bm25 * (1.0 / (rank + 1))
            if key not in doc_map:
                doc_map[key] = doc

        # 按融合分数降序排列
        sorted_keys = sorted(scores, key=scores.get, reverse=True)
        merged = []
        for key in sorted_keys[:top_k]:
            doc = doc_map[key]
            doc.metadata["relevance_score"] = round(scores[key], 4)
            merged.append(doc)
        return merged

    async def _maybe_rewrite_query(self, query: str) -> str:
        """可选地改写查询以获得更好的检索效果（使用 7b）。"""
        try:
            from .query_rewriter import rewrite_query

            rewritten = await rewrite_query(query)
            if rewritten and rewritten != query:
                logger.debug(f"[RAG] Query rewritten: '{query}' → '{rewritten}'")
                return rewritten
        except Exception:
            pass  # 任何错误都跳过改写
        return query


# =============================================================================
# 单例
# =============================================================================

_engine_instance: Optional[RAGEngine] = None


def get_rag_engine() -> Optional[RAGEngine]:
    """获取 RAG 引擎单例（懒初始化）。"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = RAGEngine()
    return _engine_instance
