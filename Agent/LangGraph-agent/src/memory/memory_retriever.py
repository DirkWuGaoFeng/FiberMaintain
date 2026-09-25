"""
MemoryRetriever — 语义记忆检索器 [P0-B].

扩展 ExperienceStore 的检索能力：
1. 向量语义搜索：用 embedding 对经验结论进行语义匹配
2. 模糊匹配：支持 fiber_id 列表的跨记录检索
3. 内容相似度去重：比较结论文本相似度而非仅 severity

设计原则：
- 确定性优先：精确匹配仍作为快速路径
- 渐进增强：向量搜索作为补充，不替代精确匹配
- 优雅降级：embedding 不可用时退化为关键词匹配

【面试知识点】
  Q: 为什么需要语义检索？
  A: ExperienceStore 原来只能精确匹配 fiber_key。当用户问「光纤 5 和 6 的问题」时，
     精确匹配 "5,6" 查不到 "5" 和 "6" 分别的历史经验。语义检索通过 embedding
     找到语义相似的经验，即使 fiber_key 不完全匹配。
  Q: 为什么用 sqlite-vec？
  A: 轻量级，无需额外服务（ChromaDB/FAISS）。适合 Agent 场景下的中等规模记忆检索。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

MEMORY_DB = str(DATA_DIR / "memory.db")
MAX_EVIDENCE_CHARS = 1000
MAX_SUMMARY_CHARS = 300
SIMILARITY_THRESHOLD = 0.7  # 语义相似度阈值
BM25_TOP_K = 5


class MemoryRetriever:
    """语义记忆检索器 [P0-B].

    使用方式：
        retriever = MemoryRetriever()
        # 精确匹配（快速路径）
        results = retriever.query_exact("5")
        # 语义检索（跨 fiber 匹配）
        results = retriever.query_semantic("分析光纤5衰耗异常")
        # 混合检索（精确 + 语义）
        results = retriever.query_hybrid("5", "衰耗异常")
    """

    def __init__(self, db_path: str = MEMORY_DB):
        self._db_path = db_path
        self._embedding_model = None
        self._embedding_dim = 1024
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构（兼容旧版 ExperienceStore schema）."""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_experiences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fiber_key TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    conclusion TEXT NOT NULL,
                    evidence TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            # 检查并添加 embedding 列（兼容旧版 schema）
            columns = [row[1] for row in conn.execute("PRAGMA table_info(analysis_experiences)").fetchall()]
            if "embedding" not in columns:
                conn.execute("ALTER TABLE analysis_experiences ADD COLUMN embedding BLOB DEFAULT NULL")
                logger.info("[MemoryRetriever] Added 'embedding' column to analysis_experiences")

            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_fiber " "ON analysis_experiences(fiber_key)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_severity " "ON analysis_experiences(severity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_created " "ON analysis_experiences(created_at DESC)")
        finally:
            conn.close()

    def _get_embedding_model(self):
        """懒加载 embedding 模型."""
        if self._embedding_model is None:
            try:
                from ..llm.provider import get_embedding_model

                self._embedding_model = get_embedding_model()
                logger.info("[MemoryRetriever] Embedding model initialized")
            except Exception as e:
                logger.warning(f"[MemoryRetriever] Embedding model not available: {e}")
        return self._embedding_model

    async def _embed_text(self, text: str) -> Optional[list[float]]:
        """将文本转为 embedding 向量."""
        model = self._get_embedding_model()
        if model is None:
            return None
        try:
            embedding = await model.aembed_query(text)
            return embedding
        except Exception as e:
            logger.warning(f"[MemoryRetriever] Embedding failed: {e}")
            return None

    def _cosine_similarity(self, vec_a: list[float], vec_b: list[float]) -> float:
        """计算两个向量的余弦相似度."""
        import math

        if not vec_a or not vec_b or len(vec_a) != len(vec_b):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = math.sqrt(sum(a * a for a in vec_a))
        norm_b = math.sqrt(sum(b * b for b in vec_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot_product / (norm_a * norm_b)

    # =========================================================================
    # 写入（带 embedding 生成）
    # =========================================================================

    async def save(
        self,
        fiber_key: str,
        severity: str,
        conclusion: str,
        evidence: list | None = None,
        auto_embed: bool = True,
    ) -> bool:
        """保存经验（带可选 embedding 生成）.

        Args:
            fiber_key: 光纤标识符
            severity: 严重程度 (WARNING/CRITICAL)
            conclusion: 结论文本
            evidence: 证据列表
            auto_embed: 是否自动生成 embedding

        Returns:
            是否保存成功
        """
        if not fiber_key or severity not in ("WARNING", "CRITICAL"):
            return False

        conn = sqlite3.connect(self._db_path)
        try:
            # 去重检查：比较结论文本相似度
            latest = conn.execute(
                "SELECT conclusion, severity FROM analysis_experiences " "WHERE fiber_key = ? ORDER BY id DESC LIMIT 1",
                (fiber_key,),
            ).fetchone()

            if latest:
                latest_conclusion = latest["conclusion"] if "conclusion" in latest.keys() else latest[0]
                latest_severity = latest["severity"] if "severity" in latest.keys() else latest[1]

                # 同 severity 且文本相似度高 → 跳过
                if latest_severity == severity:
                    similarity = self._text_similarity(conclusion, latest_conclusion)
                    if similarity > 0.85:
                        logger.debug(f"[MemoryRetriever] Dedup skip: " f"{fiber_key} sim={similarity:.2f}")
                        return False

            # 生成 embedding
            embedding_blob = None
            if auto_embed:
                vec = await self._embed_text(conclusion)
                if vec:
                    import struct

                    embedding_blob = struct.pack(f"{len(vec)}f", *vec)

            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fiber_key,
                    severity,
                    conclusion[:MAX_SUMMARY_CHARS],
                    json.dumps(evidence or [], ensure_ascii=False)[:MAX_EVIDENCE_CHARS],
                    datetime.now().isoformat(),
                    embedding_blob,
                ),
            )
            conn.commit()
            logger.info(f"[MemoryRetriever] Saved {severity} experience for {fiber_key}")
            return True
        finally:
            conn.close()

    @staticmethod
    def _text_similarity(text_a: str, text_b: str) -> float:
        """基于 Jaccard 的文本相似度（确定性，零 LLM）."""
        set_a = set(text_a.lower().split())
        set_b = set(text_b.lower().split())
        if not set_a or not set_b:
            return 0.0
        intersection = set_a & set_b
        union = set_a | set_b
        return len(intersection) / len(union)

    # =========================================================================
    # 精确匹配（快速路径）
    # =========================================================================

    def query_exact(self, fiber_key: str, days: int = 90, limit: int = 5) -> list[dict]:
        """精确匹配 fiber_key（向后兼容）."""
        if not fiber_key:
            return []
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            rows = conn.execute(
                "SELECT severity, conclusion, evidence, created_at "
                "FROM analysis_experiences "
                "WHERE fiber_key = ? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (fiber_key, since, limit),
            ).fetchall()
            return [
                {
                    "severity": r["severity"],
                    "conclusion": r["conclusion"],
                    "evidence": json.loads(r["evidence"] or "[]"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # =========================================================================
    # 模糊匹配（跨 fiber 检索）
    # =========================================================================

    def query_fuzzy(
        self,
        fiber_keys: list[str],
        days: int = 90,
        limit: int = 10,
    ) -> list[dict]:
        """模糊匹配：检索多个 fiber_key 的所有经验.

        Args:
            fiber_keys: 光纤 ID 列表
            days: 回溯天数
            limit: 最大返回数量

        Returns:
            按时间倒序排列的经验列表
        """
        if not fiber_keys:
            return []

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            placeholders = ",".join("?" * len(fiber_keys))
            rows = conn.execute(
                f"SELECT fiber_key, severity, conclusion, evidence, created_at "
                f"FROM analysis_experiences "
                f"WHERE fiber_key IN ({placeholders}) AND created_at >= ? "
                f"ORDER BY created_at DESC LIMIT ?",
                (*fiber_keys, since, limit),
            ).fetchall()
            return [
                {
                    "fiber_key": r["fiber_key"],
                    "severity": r["severity"],
                    "conclusion": r["conclusion"],
                    "evidence": json.loads(r["evidence"] or "[]"),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        finally:
            conn.close()

    # =========================================================================
    # 语义检索（基于 embedding）
    # =========================================================================

    async def query_semantic(
        self,
        query_text: str,
        fiber_keys: list[str] | None = None,
        days: int = 90,
        top_k: int = BM25_TOP_K,
        min_similarity: float = SIMILARITY_THRESHOLD,
    ) -> list[dict]:
        """语义检索：基于 embedding 找到语义相似的经验.

        Args:
            query_text: 查询文本
            fiber_keys: 可选的 fiber_key 过滤器
            days: 回溯天数
            top_k: 返回数量
            min_similarity: 最低相似度阈值

        Returns:
            按相似度排序的经验列表
        """
        # 生成查询 embedding
        query_vec = await self._embed_text(query_text)
        if query_vec is None:
            # Fallback: 关键词匹配
            logger.warning("[MemoryRetriever] Embedding not available, " "falling back to keyword search")
            return self._keyword_search(query_text, fiber_keys, days, top_k)

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()

            # 获取候选记录
            if fiber_keys:
                placeholders = ",".join("?" * len(fiber_keys))
                rows = conn.execute(
                    f"SELECT fiber_key, severity, conclusion, evidence, "
                    f"created_at, embedding "
                    f"FROM analysis_experiences "
                    f"WHERE fiber_key IN ({placeholders}) "
                    f"AND created_at >= ? AND embedding IS NOT NULL",
                    (*fiber_keys, since),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT fiber_key, severity, conclusion, evidence, "
                    "created_at, embedding "
                    "FROM analysis_experiences "
                    "WHERE created_at >= ? AND embedding IS NOT NULL",
                    (since,),
                ).fetchall()

            # 计算相似度并排序
            results = []
            for row in rows:
                if row["embedding"] is None:
                    continue
                import struct

                stored_vec = list(struct.unpack(f"{len(query_vec)}f", row["embedding"]))
                similarity = self._cosine_similarity(query_vec, stored_vec)
                if similarity >= min_similarity:
                    results.append(
                        {
                            "fiber_key": row["fiber_key"],
                            "severity": row["severity"],
                            "conclusion": row["conclusion"],
                            "evidence": json.loads(row["evidence"] or "[]"),
                            "created_at": row["created_at"],
                            "similarity": round(similarity, 4),
                        }
                    )

            # 按相似度排序
            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:top_k]

        finally:
            conn.close()

    def _keyword_search(
        self,
        query_text: str,
        fiber_keys: list[str] | None = None,
        days: int = 90,
        top_k: int = BM25_TOP_K,
    ) -> list[dict]:
        """关键词匹配（embedding 不可用时的降级方案）."""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            keywords = [w for w in query_text.lower().split() if len(w) > 1]

            if not keywords:
                return []

            conditions = " OR ".join(["conclusion LIKE ?" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]

            if fiber_keys:
                placeholders = ",".join("?" * len(fiber_keys))
                sql = (
                    f"SELECT fiber_key, severity, conclusion, evidence, created_at "
                    f"FROM analysis_experiences "
                    f"WHERE fiber_key IN ({placeholders}) "
                    f"AND created_at >= ? "
                    f"AND ({conditions}) "
                    f"ORDER BY created_at DESC LIMIT ?"
                )
                params = fiber_keys + [since] + params + [top_k]
            else:
                sql = (
                    "SELECT fiber_key, severity, conclusion, evidence, created_at "
                    "FROM analysis_experiences "
                    "WHERE created_at >= ? "
                    f"AND ({conditions}) "
                    "ORDER BY created_at DESC LIMIT ?"
                )
                params = [since] + params + [top_k]

            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "fiber_key": r["fiber_key"],
                    "severity": r["severity"],
                    "conclusion": r["conclusion"],
                    "evidence": json.loads(r["evidence"] or "[]"),
                    "created_at": r["created_at"],
                    "similarity": 0.0,
                }
                for r in rows
            ]
        finally:
            conn.close()

    # =========================================================================
    # 混合检索（推荐入口）
    # =========================================================================

    async def query_hybrid(
        self,
        fiber_key: str,
        query_text: str = "",
        days: int = 90,
        top_k: int = 5,
    ) -> list[dict]:
        """混合检索：精确 + 语义.

        优先精确匹配，若结果不足用语义检索补充.
        """
        # Phase 1: 精确匹配
        exact_results = self.query_exact(fiber_key, days=days, limit=top_k)

        # 如果有查询文本，用语义检索补充
        if query_text and len(exact_results) < top_k:
            semantic_results = await self.query_semantic(
                query_text,
                fiber_keys=[fiber_key] if fiber_key else None,
                days=days,
                top_k=top_k - len(exact_results),
            )
            # 去重合并
            seen_ids = {r["conclusion"] + r["created_at"] for r in exact_results}
            for sr in semantic_results:
                key = sr["conclusion"] + sr["created_at"]
                if key not in seen_ids:
                    exact_results.append(sr)
                    seen_ids.add(key)

        return exact_results[:top_k]

    def latest_severity(self, fiber_key: str) -> Optional[str]:
        """获取最新的严重程度."""
        if not fiber_key:
            return None
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT severity FROM analysis_experiences " "WHERE fiber_key = ? ORDER BY id DESC LIMIT 1",
                (fiber_key,),
            ).fetchone()
            return row["severity"] if row else None
        finally:
            conn.close()


# =============================================================================
# 全局单例
# =============================================================================

_retriever_instance: Optional[MemoryRetriever] = None


def get_memory_retriever() -> MemoryRetriever:
    """获取全局 MemoryRetriever 单例."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = MemoryRetriever()
    return _retriever_instance
