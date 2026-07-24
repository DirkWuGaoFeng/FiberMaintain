"""RAGInjectionMiddleware：before_model 关键词触发知识注入（§5.3）。"""
from __future__ import annotations
import logging
from .base import Middleware, RunContext
from src.rag.engine import rag_engine
from src.settings import settings
from src.monitoring.metrics import RAG_DURATION

logger = logging.getLogger("fiber.mw.rag")

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
    import re
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'[a-zA-Z]+', text))
    other_chars = len(text) - chinese_chars - english_words
    return int(chinese_chars * 1.5 + english_words + other_chars * 0.5)

class RAGInjectionMiddleware(Middleware):

    async def before_model(self, ctx: RunContext) -> None:
        # 仅取最新用户消息做关键词匹配
        user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
        if not user_msgs:
            return
        text = user_msgs[-1].get("content", "").lower()

        collections: list[str] = []
        for keywords, cols in KEYWORD_MAP:
            if any(k in text for k in keywords):
                collections.extend(cols)
        if not collections:
            return
        collections = list(dict.fromkeys(collections))

        with RAG_DURATION.time():
            try:
                hits = await rag_engine.hybrid_search(
                    user_msgs[-1]["content"], collections,
                    top_k=settings.rag["final_top_k"])
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
            logger.info("RAG 注入 %d 条知识（%s，%d tokens）",
                       len(selected_hits), collections, total_tokens)