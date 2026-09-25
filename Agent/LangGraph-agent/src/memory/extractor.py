"""
会话后记忆提取器 (MemoryExtractor) —— 书籍 Ch3 用户记忆系统核心机制。

【设计原则】（对应《AI Agent 设计原理与工程实践》Ch3）
- 生命周期四步（书籍 43-54 行）：extract → verify → dedupe → store
    when answering:  recent_turns + relevant_memory → LLM 回答（在线，不阻塞）
    after conversation (background job):
        candidates = extract_memory_candidates(conversation)   # 提取候选
        verified   = verify_against_sources_and_policy(...)    # 审核（质量门禁）
        memory.append_or_update(verified)                       # 写入/更新
- 选择性：只保留跨会话有价值的稳定事实（丢弃"搜索返回3个选项"类短期细节）
- 抽象化：把"靠窗座位"归纳为长期偏好，而非逐句保存
- 结构化：用可检索的字段（type + key + value）保存事实

【与经验库的区别】
- experience_store：故障处理经验的集体记忆（WARNING/CRITICAL 才入库，质量 veto）
- user_memory_store：用户个性化偏好/事实（本提取器写入的目标）
- 本提取器只负责"从对话提取用户个性化记忆"，与经验库互不干扰

【质量门禁（verify）】
- 空候选/空 value 拒绝
- 置信度低于阈值拒绝（防 LLM 幻觉）
- 结构化字段缺失拒绝
- 对输出格式/语言等关键偏好做白名单归一化（防脏数据污染注入逻辑）

【安全性】
- 提取本身是后台任务，失败绝不阻塞在线推理（外层 try/except）
- 提取的偏好写入前经 output_filter 脱敏（PII 保护）
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# =============================================================================
# 提取结果的数据结构
# =============================================================================

# 记忆类别（书籍"选择性/抽象化/结构化"三原则的落地）
MEMORY_TYPES = ("preference", "fact", "activity")


class MemoryCandidate(BaseModel):
    """一条候选记忆（LLM 提取的结构化输出）。"""

    type: str = Field(..., description="记忆类别: preference/fact/activity")
    key: str = Field(..., description="稳定键, 如 default_format / language")
    value: str = Field(..., description="记忆值, 如 table / 中文")
    confidence: float = Field(0.7, ge=0.0, le=1.0)
    source: str = Field("", description="来源: 对话摘录/系统上下文")


class MemoryCandidateList(BaseModel):
    """一次提取的候选记忆列表。"""

    candidates: list[MemoryCandidate] = Field(default_factory=list)


# 置信度阈值：低于此值的候选视为不可靠，拒绝写入
_CONFIDENCE_THRESHOLD = 0.6

# 偏好白名单：仅这些 key 允许直接写入 preferences（防止任意键污染注入逻辑）
# 与 user_memory.inject_preferences 读取的字段保持一致
_PREFERENCE_WHITELIST = frozenset(
    {
        "default_format",
        "notify_severity",
        "language",
    }
)

# 结构化字段白名单：key 需符合 [a-z_]{1,40} 模式
_VALID_KEY_RE = "^[a-z_][a-z0-9_]{0,39}$"

import re  # noqa: E402


class MemoryExtractor:
    """会话后记忆提取器：从对话中提取并入库用户个性化记忆。"""

    def __init__(
        self,
        store: Optional[Any] = None,
        llm: Optional[Any] = None,
        retriever: Optional[Any] = None,
    ):
        """注入 store / llm / retriever 便于测试；默认使用真实组件。

        retriever 用于将 fact/activity 事件写入带 embedding（供语义检索），
        与 store 共享同一 db_path。
        """
        from .user_memory_store import UserMemoryStore

        self._store = store or UserMemoryStore()
        self._llm = llm  # 惰性获取（见 _get_llm）

        if retriever is not None:
            self._retriever = retriever
        else:
            from .user_memory_retriever import UserMemoryRetriever

            # 与 store 共享同一数据库文件，保证事件写入后即可检索
            self._retriever = UserMemoryRetriever(db_path=getattr(self._store, "_db_path", None))

    # ------------------------------------------------------------------
    # LLM 获取（惰性）
    # ------------------------------------------------------------------

    def _get_llm(self):
        """获取提取用 LLM（次级模型，temperature 低保证确定性）。"""
        if self._llm is not None:
            return self._llm
        from ..llm.provider import get_secondary_llm

        self._llm = get_secondary_llm(temperature=0.1)
        return self._llm

    # ------------------------------------------------------------------
    # 第一步：提取候选记忆（LLM 结构化输出）
    # ------------------------------------------------------------------

    async def extract_candidates(
        self,
        conversation: str,
        user_id: str = "",
        max_candidates: int = 5,
    ) -> list[MemoryCandidate]:
        """从对话文本中提取候选记忆。

        【流程】
        - 构造提取提示词（system 定义类别与选择性/抽象化原则，user 放对话）
        - LLM 以结构化 JSON 输出候选列表
        - 截断到 max_candidates 条（防 LLM 一次性吐太多噪声）
        """
        from langchain_core.prompts import ChatPromptTemplate

        from ..llm.prompts import escape_for_template, load_prompt

        system = escape_for_template(
            load_prompt("memory_extractor", "system", default=_SYSTEM_FALLBACK),
            keep_vars=(),
        )
        user = escape_for_template(
            load_prompt("memory_extractor", "user", default=_USER_FALLBACK),
            keep_vars=("conversation", "user_id"),
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system),
                ("human", user),
            ]
        )

        # LLM 不可用（构建或调用阶段）都必须降级为空结果，不阻塞调用方
        try:
            chain = prompt | self._get_llm().with_structured_output(MemoryCandidateList, method="json_mode")
            result: MemoryCandidateList = await chain.ainvoke(
                {
                    "conversation": conversation,
                    "user_id": user_id,
                }
            )
        except Exception as e:
            logger.warning(f"[MemoryExtractor] LLM extract failed: {e}")
            return []

        candidates = result.candidates if result else []
        return candidates[:max_candidates]

    # ------------------------------------------------------------------
    # 第二步：审核（质量门禁）
    # ------------------------------------------------------------------

    def verify_candidate(self, cand: MemoryCandidate) -> bool:
        """单条候选质量门禁。通过返回 True。

        规则（书籍"验证再入库"思想 + 防幻觉）：
        1. type 必须在白名单内
        2. key 必须符合结构化字段命名
        3. value 非空且长度受限
        4. confidence 不低于阈值
        """
        if cand.type not in MEMORY_TYPES:
            return False
        if not re.match(_VALID_KEY_RE, cand.key or ""):
            return False
        value = (cand.value or "").strip()
        if not value or len(value) > 200:
            return False
        if cand.confidence < _CONFIDENCE_THRESHOLD:
            return False
        return True

    def verify_candidates(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        """批量审核，仅返回通过质量门禁的候选。"""
        return [c for c in candidates if self.verify_candidate(c)]

    # ------------------------------------------------------------------
    # 第三步：去重
    # ------------------------------------------------------------------

    @staticmethod
    def dedupe_candidates(
        candidates: list[MemoryCandidate],
    ) -> list[MemoryCandidate]:
        """按 (type, key) 去重，保留 confidence 最高的一条。"""
        best: dict[tuple[str, str], MemoryCandidate] = {}
        for c in candidates:
            cur = best.get((c.type, c.key))
            if cur is None or c.confidence > cur.confidence:
                best[(c.type, c.key)] = c
        return list(best.values())

    # ------------------------------------------------------------------
    # 第四步：写入（带白名单与脱敏）
    # ------------------------------------------------------------------

    def store_candidates(
        self,
        user_id: str,
        candidates: list[MemoryCandidate],
    ) -> dict[str, int]:
        """写入用户记忆。

        - preference 类：仅白名单 key 写入 preferences（其余丢弃，防脏键污染注入）
        - fact / activity 类：写入 history 事件日志
        - 写入前经 output_filter 脱敏（PII 保护）
        """
        from ..security.output_filter import output_filter
        from .user_memory import get_user_memory_manager

        manager = get_user_memory_manager()
        # 注入自定义 store 以便测试隔离
        manager._store = self._store

        written_prefs = 0
        written_events = 0

        for cand in candidates:
            value = output_filter.filter((cand.value or "").strip())
            if not value:
                continue

            if cand.type == "preference":
                # 仅白名单偏好写入（防止任意键污染注入逻辑）
                if cand.key not in _PREFERENCE_WHITELIST:
                    logger.debug(f"[MemoryExtractor] Skip non-whitelisted preference: " f"{cand.key}")
                    continue
                try:
                    manager.update_preference(user_id, cand.key, value)
                    written_prefs += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[MemoryExtractor] Preference write failed: {e}")
            else:
                # fact / activity → 事件日志（同步写入，保证不依赖事件循环）
                try:
                    self._store.log_event(
                        user_id,
                        event_type=f"memory.{cand.type}",
                        details={
                            "key": cand.key,
                            "value": value,
                            "source": cand.source,
                            "confidence": cand.confidence,
                        },
                    )
                    self._store.add_history(
                        user_id,
                        {
                            "event_type": f"memory.{cand.type}",
                            "details": {
                                "key": cand.key,
                                "value": value,
                                "source": cand.source,
                                "confidence": cand.confidence,
                            },
                        },
                    )
                    written_events += 1
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[MemoryExtractor] Event write failed: {e}")

        return {"preferences": written_prefs, "events": written_events}

    # ------------------------------------------------------------------
    # 第四步补充：为写入的事件生成 embedding（供语义检索）[P0-2]
    # ------------------------------------------------------------------

    async def enrich_events_with_embedding(
        self,
        user_id: str,
        event_types: tuple[str, ...] = ("memory.fact", "memory.activity"),
    ) -> int:
        """为最近写入的用户事件补生成 embedding（幂等，仅处理缺失的）。

        【背景】store_candidates 同步写事件以保证不阻塞；但语义检索依赖
        embedding 列。本方法在后台（async）为缺失 embedding 的事件补向量，
        使 extract_and_store 完成后事件即可被 query_hybrid 检索。

        【幂等性】只处理 embedding IS NULL 的事件，重复调用不重复计算。
        """
        try:
            return await self._retriever.backfill_embeddings(user_id, event_types=event_types)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[MemoryExtractor] Embedding backfill failed: {e}")
            return 0

    # ------------------------------------------------------------------
    # 完整流水线：extract → verify → dedupe → store
    # ------------------------------------------------------------------

    async def extract_and_store(
        self,
        conversation: str,
        user_id: str = "",
        max_candidates: int = 5,
    ) -> dict[str, Any]:
        """完整执行记忆提取流水线。

        【返回】统计字典：
            extracted / verified / stored_prefs / stored_events
        全程异常安全：任何一步失败都返回部分统计而非抛出，不阻塞调用方。
        """
        # 1. 提取
        candidates = await self.extract_candidates(conversation, user_id, max_candidates)

        # 2. 审核
        verified = self.verify_candidates(candidates)

        # 3. 去重
        deduped = self.dedupe_candidates(verified)

        # 4. 写入
        written = self.store_candidates(user_id, deduped) if deduped else {"preferences": 0, "events": 0}

        # 5. 为事件补 embedding（供语义检索）[P0-2]
        #    同步写入保证事件立即可查；embedding 后台补向量，失败不阻塞
        backfilled = 0
        if written["events"] > 0:
            backfilled = await self.enrich_events_with_embedding(user_id)

        logger.info(
            f"[MemoryExtractor] user={user_id} extracted={len(candidates)} "
            f"verified={len(verified)} prefs={written['preferences']} "
            f"events={written['events']} backfilled={backfilled}"
        )
        return {
            "extracted": len(candidates),
            "verified": len(verified),
            "stored_prefs": written["preferences"],
            "stored_events": written["events"],
            "backfilled_embeddings": backfilled,
        }


# =============================================================================
# 提示词（兜底，prompts/memory_extractor/*.md 缺失时使用）
# =============================================================================

_SYSTEM_FALLBACK = """你是用户记忆提取器。从用户与光纤维护 Agent 的对话中，
提取值得跨会话长期记住的用户个性化信息。

仅提取三类（输出 JSON）：
- preference: 长期偏好（输出格式、通知级别、语言、沟通风格等）
- fact: 稳定事实（用户负责的区域、常用光纤编号、部门等）
- activity: 近期活动（最近执行的维护、关注的设备等）

遵循三条规则：
1. 选择性：只保留跨会话有价值的信息，丢弃一次性细节
2. 抽象化：把具体表述归纳为长期偏好（如"喜欢表格"→"输出偏好表格"）
3. 结构化：每个候选给出稳定 key 和 value
对每类输出 confidence(0-1) 和 source(对话摘录)。"""

_USER_FALLBACK = """## 对话内容
{conversation}

请提取该用户的长期记忆候选（JSON 数组，最多 5 条）。
仅提取对话中明确出现或可靠推断的信息，不确定时 confidence 调低。"""


# 模块级单例
_extractor: Optional[MemoryExtractor] = None


def get_memory_extractor() -> MemoryExtractor:
    """获取全局提取器单例。"""
    global _extractor
    if _extractor is None:
        _extractor = MemoryExtractor()
    return _extractor
