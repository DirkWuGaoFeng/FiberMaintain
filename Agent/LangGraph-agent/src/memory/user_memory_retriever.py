"""
用户记忆语义检索器 (UserMemoryRetriever) —— 书籍 Ch3 用户记忆 RAG [P0-2].

【设计原则】（对应《AI Agent 设计原理与工程实践》Ch3 实验 3-9/3-11）
- 把用户的历史事件（user_event_log，由提取器写入的 fact/activity）视为
  可检索的长期记忆库，在注入偏好前按当前问题语义召回相关事件
- 双层记忆架构（书籍 700-709 行）：
    概览层 = preferences（常驻上下文，白名单偏好）
    细节层 = user_event_log（按需语义检索，返回相关历史事件）
- 混合检索（书籍 455-474 行）：语义优先 + 关键词兜底（embedding 不可用降级）
- 渐进增强：向量检索作为对精确事件查询的补充，不替代基础事件查询

【与 MemoryRetriever 的关系】
- MemoryRetriever: 检索 analysis_experiences（集体经验，fiber_key 维度）
- UserMemoryRetriever: 检索 user_event_log（用户个性化事件，user_id 维度）
  两者共用 embedding 生成逻辑，但表结构、查询维度、语义完全不同。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Optional

from ..config import USER_MEMORY_DB

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.6  # 语义相似度阈值
KEYWORD_TOP_K = 5


class UserMemoryRetriever:
    """用户记忆语义检索器：对 user_event_log 做向量检索。

    使用方式：
        retriever = UserMemoryRetriever()
        # 写入事件（带 embedding 生成）
        await retriever.save_event("u-1", "memory.fact", {"key": "region", "value": "华东"})
        # 语义检索（按当前问题召回相关历史事件）
        results = await retriever.query_hybrid("u-1", "用户负责哪个机房")
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or USER_MEMORY_DB
        self._embedding_model = None
        self._init_db()

    def _init_db(self) -> None:
        """初始化 user_event_log 表，并兼容性添加 embedding 列。"""
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_event_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL
                )
                """
            )
            # 兼容旧 schema：添加 embedding 列
            columns = [row[1] for row in conn.execute("PRAGMA table_info(user_event_log)").fetchall()]
            if "embedding" not in columns:
                conn.execute("ALTER TABLE user_event_log ADD COLUMN embedding BLOB DEFAULT NULL")
                logger.info("[UserMemoryRetriever] Added 'embedding' column to user_event_log")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_event_user " "ON user_event_log(user_id)")
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # embedding 能力（与 MemoryRetriever 同源）
    # ------------------------------------------------------------------

    def _get_embedding_model(self):
        """懒加载 embedding 模型."""
        if self._embedding_model is None:
            try:
                from ..llm.provider import get_embedding_model

                self._embedding_model = get_embedding_model()
                logger.info("[UserMemoryRetriever] Embedding model initialized")
            except Exception as e:
                logger.warning(f"[UserMemoryRetriever] Embedding model not available: {e}")
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
            logger.warning(f"[UserMemoryRetriever] Embedding failed: {e}")
            return None

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
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

    # ------------------------------------------------------------------
    # 写入（带 embedding 生成）
    # ------------------------------------------------------------------

    async def save_event(
        self,
        user_id: str,
        event_type: str,
        details: dict,
        auto_embed: bool = True,
    ) -> bool:
        """写入用户事件日志（带可选 embedding 生成）.

        与 UserMemoryStore.record_event 语义一致，但额外为事件内容生成
        embedding 存入库中，供后续语义检索使用。

        Args:
            user_id: 用户 ID
            event_type: 事件类型（如 memory.fact / memory.activity）
            details: 事件详情（含 key/value/source/confidence）
            auto_embed: 是否自动生成 embedding
        """
        # 通过 UserMemoryStore 走标准的 log_event + add_history 路径，
        # 保证与既有事件查询（query_events）行为一致
        from .user_memory_store import UserMemoryStore

        store = UserMemoryStore(db_path=self._db_path)
        store.log_event(user_id, event_type, details)
        store.add_history(
            user_id,
            {
                "event_type": event_type,
                "details": details,
            },
        )

        # 额外写入 embedding（仅对当前插入的最新事件）
        if auto_embed:
            vec = await self._embed_text(f"{event_type} {details.get('key', '')} {details.get('value', '')}")
            if vec:
                import struct

                conn = sqlite3.connect(self._db_path)
                try:
                    conn.execute(
                        "UPDATE user_event_log SET embedding = ? "
                        "WHERE id = (SELECT MAX(id) FROM user_event_log "
                        "WHERE user_id = ?)",
                        (struct.pack(f"{len(vec)}f", *vec), user_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
        return True

    # ------------------------------------------------------------------
    # 批量回填 embedding（幂等）
    # ------------------------------------------------------------------

    async def backfill_embeddings(
        self,
        user_id: str,
        event_types: tuple[str, ...] = ("memory.fact", "memory.activity"),
        limit: int = 50,
    ) -> int:
        """为缺失 embedding 的用户事件补生成向量（幂等）。

        只处理 embedding IS NULL 的事件；embedding 不可用或失败时跳过。
        返回成功回填的数量。
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            placeholders = ",".join("?" * len(event_types))
            rows = conn.execute(
                f"SELECT id, event_type, details FROM user_event_log "
                f"WHERE user_id = ? AND event_type IN ({placeholders}) "
                f"AND embedding IS NULL ORDER BY id DESC LIMIT ?",
                (user_id, *event_types, limit),
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            return 0

        filled = 0
        for row in rows:
            details = json.loads(row["details"] or "{}")
            text = f"{row['event_type']} {details.get('key', '')} " f"{details.get('value', '')}"
            vec = await self._embed_text(text)
            if vec:
                import struct

                conn = sqlite3.connect(self._db_path)
                try:
                    conn.execute(
                        "UPDATE user_event_log SET embedding = ? WHERE id = ?",
                        (struct.pack(f"{len(vec)}f", *vec), row["id"]),
                    )
                    conn.commit()
                    filled += 1
                finally:
                    conn.close()
        if filled:
            logger.info(f"[UserMemoryRetriever] Backfilled {filled} event embeddings " f"for user={user_id}")
        return filled

    # ------------------------------------------------------------------
    # 语义检索
    # ------------------------------------------------------------------

    async def query_semantic(
        self,
        user_id: str,
        query_text: str,
        days: int = 180,
        top_k: int = KEYWORD_TOP_K,
        min_similarity: float = SIMILARITY_THRESHOLD,
    ) -> list[dict]:
        """语义检索：按查询文本召回用户相关历史事件.

        Args:
            user_id: 用户 ID
            query_text: 查询文本（如当前用户问题）
            days: 回溯天数
            top_k: 返回数量
            min_similarity: 最低相似度阈值

        Returns:
            按相似度排序的事件列表
        """
        query_vec = await self._embed_text(query_text)
        if query_vec is None:
            logger.warning("[UserMemoryRetriever] Embedding not available, " "falling back to keyword search")
            return self.query_keyword(user_id, query_text, days, top_k)

        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            since = datetime.now().timestamp() - days * 86400
            rows = conn.execute(
                "SELECT id, user_id, event_type, details, created_at, embedding "
                "FROM user_event_log "
                "WHERE user_id = ? AND created_at >= ? AND embedding IS NOT NULL",
                (user_id, since),
            ).fetchall()

            results = []
            for row in rows:
                if row["embedding"] is None:
                    continue
                import struct

                try:
                    stored_vec = list(struct.unpack(f"{len(query_vec)}f", row["embedding"]))
                except struct.error:
                    continue
                similarity = self._cosine_similarity(query_vec, stored_vec)
                if similarity >= min_similarity:
                    results.append(
                        {
                            "id": row["id"],
                            "event_type": row["event_type"],
                            "details": json.loads(row["details"] or "{}"),
                            "created_at": row["created_at"],
                            "similarity": round(similarity, 4),
                        }
                    )

            results.sort(key=lambda x: x["similarity"], reverse=True)
            return results[:top_k]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 关键词检索（embedding 不可用时的降级方案）
    # ------------------------------------------------------------------

    def query_keyword(
        self,
        user_id: str,
        query_text: str,
        days: int = 180,
        top_k: int = KEYWORD_TOP_K,
    ) -> list[dict]:
        """关键词匹配（降级方案）：匹配 details 中的 key/value 文本.

        注意：UserMemoryStore.log_event 以 ensure_ascii=True 存储详情 JSON，
        中文会被转义为 \\uXXXX。因此关键词同时以原文与 JSON 转义两种形式
        参与 LIKE 匹配，保证中文关键词也能命中。
        """
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            since = datetime.now().timestamp() - days * 86400
            keywords = [w for w in query_text.strip().split() if len(w) > 1]
            if not keywords:
                return []

            # 每个关键词同时生成原文 + JSON 转义两种匹配模式
            patterns: list[str] = []
            for kw in keywords:
                patterns.append(f"%{kw}%")
                escaped = json.dumps(kw, ensure_ascii=True)[1:-1]  # 去掉引号
                if escaped != kw:
                    patterns.append(f"%{escaped}%")

            conditions = " OR ".join(["details LIKE ?" for _ in patterns])
            params = patterns
            rows = conn.execute(
                f"SELECT id, event_type, details, created_at "
                f"FROM user_event_log "
                f"WHERE user_id = ? AND created_at >= ? AND ({conditions}) "
                f"ORDER BY created_at DESC LIMIT ?",
                (user_id, since, *params, top_k),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "event_type": r["event_type"],
                    "details": json.loads(r["details"] or "{}"),
                    "created_at": r["created_at"],
                    "similarity": 0.0,
                }
                for r in rows
            ]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 混合检索（推荐入口）：语义优先 + 关键词补充
    # ------------------------------------------------------------------

    async def query_hybrid(
        self,
        user_id: str,
        query_text: str,
        days: int = 180,
        top_k: int = KEYWORD_TOP_K,
    ) -> list[dict]:
        """混合检索：语义结果不足时用关键词补充.

        Args:
            user_id: 用户 ID
            query_text: 查询文本
            days: 回溯天数
            top_k: 返回数量
        """
        if not user_id or not (query_text or "").strip():
            return []

        semantic = await self.query_semantic(user_id, query_text, days=days, top_k=top_k)
        # 语义结果充足或 embedding 可用时直接返回
        if len(semantic) >= top_k:
            return semantic[:top_k]

        # 补充关键词结果
        keyword = self.query_keyword(user_id, query_text, days, top_k)
        seen_ids = {r["id"] for r in semantic}
        merged = list(semantic)
        for kr in keyword:
            if kr["id"] not in seen_ids:
                merged.append(kr)
                seen_ids.add(kr["id"])
            if len(merged) >= top_k:
                break
        return merged[:top_k]


# =============================================================================
# 全局单例
# =============================================================================

_retriever_instance: Optional[UserMemoryRetriever] = None


def get_user_memory_retriever() -> UserMemoryRetriever:
    """获取全局 UserMemoryRetriever 单例."""
    global _retriever_instance
    if _retriever_instance is None:
        _retriever_instance = UserMemoryRetriever()
    return _retriever_instance
