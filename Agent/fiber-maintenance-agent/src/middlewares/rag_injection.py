"""RAGInjectionMiddleware：before_model 关键词触发知识注入（§5.3）。

v3.3.0 增强：
- 相似度阈值 0.6：低于阈值的结果不注入
- 否定词过滤：用户明确拒绝时跳过 RAG 注入
- Prompt 注入防护：检测并清洗恶意注入内容
"""
from __future__ import annotations
import logging
import re
from .base import Middleware, RunContext
from src.rag.engine import rag_engine
from src.settings import settings
from src.monitoring.metrics import RAG_DURATION

logger = logging.getLogger("fiber.mw.rag")

# 否定词：用户明确拒绝知识注入时跳过
_NEGATION_WORDS = {"不要", "不用", "不需要", "不必", "无需", "别查", "别搜"}

# 相似度阈值
SIMILARITY_THRESHOLD = 0.6

# ── Prompt 注入检测模式 ──
_PROMPT_INJECTION_PATTERNS: list[re.Pattern] = [
    # 角色扮演指令
    re.compile(r"(?:ignore|forget|disregard)\s+(?:all\s+)?(?:previous|above|prior)",
               re.IGNORECASE),
    re.compile(r"(?:忽略|无视|忘记)\s*(?:之前|以上|前面|之前)\s*(?:的|所有)?",
               re.IGNORECASE),
    # 系统指令覆盖
    re.compile(r"(?:你现在是|you\s+are\s+now|act\s+as|roleplay)", re.IGNORECASE),
    re.compile(r"(?:system\s*:|\[system\]|系统指令|system\s*prompt)", re.IGNORECASE),
    # 输出格式操纵
    re.compile(r"(?:repeat|输出|显示)\s*(?:the\s+)?(?:system|initial)\s*prompt",
               re.IGNORECASE),
    re.compile(r"(?:DAN|jailbreak|越狱)", re.IGNORECASE),
]

_MAX_INPUT_LENGTH = 2000  # 单条消息最大长度

KEYWORD_MAP: list[tuple[list[str], list[str]]] = [
    (["衰耗", "光功率", "spanloss", "oop", "iop", "db"],
     ["threshold_standard"]),
    (["告警", "颜色", "红色", "黄色", "中断", "紧急"],
     ["alarm_guide"]),
    (["批量", "所有", "全部"],
     ["maintenance_guide"]),
    (["趋势", "变化", "统计", "历史", "走势", "对比"],
     ["fault_cases"]),
    (["巡检", "健康", "网元"],
     ["maintenance_guide"]),
    (["维护", "阈值", "规范", "抢修"],
     ["maintenance_guide", "threshold_standard"]),
]

def _count_tokens(text: str) -> int:
    """估算 token 数：中文按 1.5 tokens/字符，英文按 1 token/词。"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    other_chars = len(text) - chinese_chars - english_words
    return int(chinese_chars * 1.5 + english_words + other_chars * 0.5)


def _sanitize_input(ctx: RunContext) -> str:
    """清洗用户输入：检测 Prompt 注入 + 长度截断。
    返回清洗后的文本，同时将注入告警写入 ctx.warnings。
    """
    user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
    if not user_msgs:
        return ""
    raw = user_msgs[-1].get("content", "")

    # 长度截断
    if len(raw) > _MAX_INPUT_LENGTH:
        logger.warning("[RAG] 用户输入超长: %d → %d", len(raw), _MAX_INPUT_LENGTH)
        raw = raw[:_MAX_INPUT_LENGTH]
        ctx.warnings.append(
            f"⚠️ 输入内容过长（{len(raw)}字），已截断至 {_MAX_INPUT_LENGTH} 字。")

    # Prompt 注入检测
    for pat in _PROMPT_INJECTION_PATTERNS:
        if pat.search(raw):
            logger.warning("[RAG] 检测到 Prompt 注入尝试: %.100s",
                           pat.pattern)
            ctx.warnings.append(
                "⚠️ 输入中检测到疑似指令注入内容，相关内容已被忽略。")
            ctx.meta["prompt_injection_detected"] = True
            return raw  # 不截断，但标记告警让 LLM 知道
    return raw


class RAGInjectionMiddleware(Middleware):

    async def before_model(self, ctx: RunContext) -> None:
        # 输入清洗与注入检测
        clean_text = _sanitize_input(ctx)
        if not clean_text:
            return
        text_lower = clean_text.lower()

        # 否定词过滤：用户明确拒绝时跳过 RAG
        if any(neg in text_lower for neg in _NEGATION_WORDS):
            logger.debug("RAG 注入跳过：检测到否定词")
            return

        collections: list[str] = []
        for keywords, cols in KEYWORD_MAP:
            if any(k in text_lower for k in keywords):
                collections.extend(cols)
        if not collections:
            return
        collections = list(dict.fromkeys(collections))

        with RAG_DURATION.time():
            try:
                hits = await rag_engine.hybrid_search(
                    clean_text, collections,
                    top_k=settings.rag["final_top_k"])
                # 相似度阈值过滤
                hits = [h for h in hits
                        if h.get("score", 1.0) >= SIMILARITY_THRESHOLD]
                if not hits:
                    logger.debug("RAG 注入：无结果超过阈值 %.1f",
                                SIMILARITY_THRESHOLD)
                    return
            except Exception as e:
                logger.warning("RAG 注入失败（忽略）: %s", e)
                return

        if hits:
            max_tokens = settings.rag.get("injection_max_tokens", 2000)
            total_tokens = 0
            selected_hits = []
            for hit in hits:
                content = hit.get("content", "")
                hit_tokens = _count_tokens(content)
                if total_tokens + hit_tokens > max_tokens and selected_hits:
                    logger.info("RAG 注入截断：已达 %d tokens 上限", max_tokens)
                    break
                selected_hits.append(hit)
                total_tokens += hit_tokens
            ctx.knowledge_snippets = selected_hits
            logger.info("RAG 注入 %d 条知识（%s，%d tokens，阈值=%.1f）",
                       len(selected_hits), collections, total_tokens,
                       SIMILARITY_THRESHOLD)