"""
LLM Provider - 三层梯度架构 [v7.1]。

Tier 1（主层）：  重推理 — 意图分类、分析、报告
Tier 2（次级）：  表达/叙述 — 叙述员、知识问答、改写
Tier 3（轻量层）：L2 降级时的应急兜底

Provider 模式（按层配置，通过 LLM_*_PROVIDER，默认 LLM_PROVIDER）：
- "ollama": 本地 Ollama（默认，qwen2.5 梯度）
- "openai": 任意 OpenAI 兼容 API（如阿里云百炼 / DashScope）
各层可混用 Provider，例如主层=Bailian API，次级/轻量层=本地 Ollama。

降级路径：主层不可用 → 次级接管 → 轻量层 → 模板
"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings

from ..config import (
    EMBEDDING_MODEL,
    LLM_CONFIG,
    OLLAMA_BASE_URL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
    LLMTierConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 三层 LLM 实例 [v7.1]
# =============================================================================


def _build_tier_llm(cfg: LLMTierConfig, temperature: float, num_ctx: int | None = None) -> BaseChatModel:
    """按该层级的 provider 构建聊天模型实例.

    ollama 层走本地 ChatOllama；openai 层走 OpenAI 兼容协议
    （阿里云百炼 DashScope compatible-mode），支持流式与工具调用。
    """
    if cfg.provider == "openai":
        from langchain_openai import ChatOpenAI

        if not OPENAI_API_KEY:
            logger.warning(f"[LLM] 层级模型 {cfg.model} 使用 openai 协议但未配置 " "OPENAI_API_KEY / DASHSCOPE_API_KEY")
        return ChatOpenAI(
            model=cfg.model,
            temperature=temperature,
            base_url=OPENAI_API_BASE,
            api_key=OPENAI_API_KEY or "EMPTY",
            timeout=cfg.timeout,
            max_retries=2,
            seed=42,  # 与 Ollama seed=42 保持确定性一致
        )

    ollama_kwargs: dict = dict(
        model=cfg.model,
        temperature=temperature,
        base_url=OLLAMA_BASE_URL,
        seed=42,
        timeout=cfg.timeout,
    )
    if num_ctx is not None:
        ollama_kwargs["num_ctx"] = num_ctx
    return ChatOllama(**ollama_kwargs)


def get_primary_llm(temperature: float | None = None) -> BaseChatModel:
    """
    主层 LLM：重推理任务。

    使用场景：意图分类、参数提取、
    分析专家、报告生成、报告评估。
    """
    cfg = LLM_CONFIG["primary"]
    return _build_tier_llm(
        cfg,
        temperature if temperature is not None else cfg.temperature,
        num_ctx=8192,
    )


def get_secondary_llm(temperature: float | None = None) -> BaseChatModel:
    """
    次级 LLM：表达/叙述任务。

    使用场景：叙述员、知识问答、查询改写、澄清。
    """
    cfg = LLM_CONFIG["secondary"]
    return _build_tier_llm(
        cfg,
        temperature if temperature is not None else cfg.temperature,
        num_ctx=4096,
    )


def get_tertiary_llm(temperature: float | None = None) -> BaseChatModel:
    """
    轻量层 LLM：仅用于应急兜底。

    使用场景：L2 降级的最小推理、模板填充。
    """
    cfg = LLM_CONFIG["tertiary"]
    return _build_tier_llm(cfg, temperature if temperature is not None else cfg.temperature)


def get_llm_with_fallback(temperature: float = 0.1) -> BaseChatModel:
    """
    获取带完整三层兜底链的 LLM。

    兜底链：主 → 次 → 末
    触发条件：TimeoutException、ConnectError
    """
    import httpx

    primary = get_primary_llm(temperature)
    secondary = get_secondary_llm(temperature)
    tertiary = get_tertiary_llm(temperature)

    return primary.with_fallbacks(
        [secondary, tertiary],
        exceptions_to_handle=(httpx.TimeoutException, httpx.ConnectError, Exception),
    )


# =============================================================================
# 专用 LLM 访问器（按各节点需求）
# =============================================================================


def get_intent_llm() -> BaseChatModel:
    """意图分类器：主层级，temperature=0.0（最高确定性）。"""
    return get_primary_llm(temperature=0.0)


def get_analysis_llm() -> BaseChatModel:
    """分析专家：主层级，temperature=0.1（轻微创造性）。"""
    return get_primary_llm(temperature=0.1)


def get_narrator_llm() -> BaseChatModel:
    """叙述员：次级层级，temperature=0.3（自然表达）。"""
    return get_secondary_llm(temperature=0.3)


def get_knowledge_llm() -> BaseChatModel:
    """知识问答：次级层级，temperature=0.5（对话式）。"""
    return get_secondary_llm(temperature=0.5)


def get_report_llm() -> BaseChatModel:
    """报告生成器：主层级，temperature=0.3（结构化写作）。"""
    return get_primary_llm(temperature=0.3)


def get_report_eval_llm() -> BaseChatModel:
    """报告评估器（反思）：主层，temperature=0.1。"""
    return get_primary_llm(temperature=0.1)


def get_query_rewriter_llm() -> BaseChatModel:
    """RAG 查询改写器：次级层级，temperature=0.1。"""
    return get_secondary_llm(temperature=0.1)


def get_data_collector_llm() -> BaseChatModel:
    """数据采集器（工具调用）：主层，temperature=0.0。"""
    return get_primary_llm(temperature=0.0)


def get_batch_llm() -> BaseChatModel:
    """批量聚合：主层级带兜底，temperature=0.1。

    返回 BaseChatModel（当主层级使用百炼 API provider 时可能为
    ChatOpenAI — [P0-D] 修复了过时的 ChatOllama 注解）。
    """
    return get_llm_with_fallback(temperature=0.1)


# =============================================================================
# Embedding 模型 [v7.1: 基于 Ollama]
# =============================================================================

_embedding_instance: OllamaEmbeddings | None = None


def get_embedding_model() -> OllamaEmbeddings:
    """
    获取 Ollama embedding 模型（bge-large 或 nomic-embed-text）。

    懒加载单例，避免在导入时加载。
    """
    global _embedding_instance
    if _embedding_instance is None:
        _embedding_instance = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        logger.info(f"[Embedding] Initialized Ollama embedding: {EMBEDDING_MODEL}")
    return _embedding_instance
