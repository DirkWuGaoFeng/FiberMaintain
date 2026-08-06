"""
LLM Provider - Three-Tier Gradient Architecture [v7.1].

Tier 1 (Primary):   reasoning-heavy — intent classification, analysis, report
Tier 2 (Secondary): expression/narration — narrator, knowledge QA, rewriting
Tier 3 (Tertiary):  emergency fallback for L2 degradation

Provider modes (per-tier, via LLM_*_PROVIDER, default LLM_PROVIDER):
- "ollama": local Ollama (default, qwen2.5 gradient)
- "openai": any OpenAI-compatible API (e.g. Alibaba Cloud Bailian / DashScope)
Tiers may mix providers, e.g. primary=Bailian API, secondary/tertiary=local Ollama.

Degradation path: primary unavailable → secondary takes over → tertiary → template
"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama, OllamaEmbeddings

from ..config import (
    EMBEDDING_MODEL,
    LLM_CONFIG,
    LLMTierConfig,
    OLLAMA_BASE_URL,
    OPENAI_API_BASE,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Three-Tier LLM Instances [v7.1]
# =============================================================================


def _build_tier_llm(
    cfg: LLMTierConfig, temperature: float, num_ctx: int | None = None
) -> BaseChatModel:
    """按该层级的 provider 构建聊天模型实例.

    ollama 层走本地 ChatOllama；openai 层走 OpenAI 兼容协议
    （阿里云百炼 DashScope compatible-mode），支持流式与工具调用。
    """
    if cfg.provider == "openai":
        from langchain_openai import ChatOpenAI

        if not OPENAI_API_KEY:
            logger.warning(
                f"[LLM] 层级模型 {cfg.model} 使用 openai 协议但未配置 "
                "OPENAI_API_KEY / DASHSCOPE_API_KEY"
            )
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
    Primary LLM: reasoning-heavy tasks.

    Use cases: intent classification, parameter extraction,
    analysis expert, report generation, report evaluation.
    """
    cfg = LLM_CONFIG["primary"]
    return _build_tier_llm(
        cfg,
        temperature if temperature is not None else cfg.temperature,
        num_ctx=8192,
    )


def get_secondary_llm(temperature: float | None = None) -> BaseChatModel:
    """
    Secondary LLM: expression/narration tasks.

    Use cases: narrator, knowledge QA, query rewriting, clarification.
    """
    cfg = LLM_CONFIG["secondary"]
    return _build_tier_llm(
        cfg,
        temperature if temperature is not None else cfg.temperature,
        num_ctx=4096,
    )


def get_tertiary_llm(temperature: float | None = None) -> BaseChatModel:
    """
    Tertiary LLM: emergency fallback only.

    Use cases: L2 degradation minimal reasoning, template filling.
    """
    cfg = LLM_CONFIG["tertiary"]
    return _build_tier_llm(
        cfg, temperature if temperature is not None else cfg.temperature
    )


def get_llm_with_fallback(temperature: float = 0.1) -> BaseChatModel:
    """
    Get LLM with full three-tier fallback chain.

    Chain: primary → secondary → tertiary
    Triggers on: TimeoutException, ConnectError
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
# Specialized LLM Accessors (per node requirements)
# =============================================================================


def get_intent_llm() -> BaseChatModel:
    """Intent classifier: primary tier, temperature=0.0 (maximum determinism)."""
    return get_primary_llm(temperature=0.0)


def get_analysis_llm() -> BaseChatModel:
    """Analysis expert: primary tier, temperature=0.1 (slight creativity)."""
    return get_primary_llm(temperature=0.1)


def get_narrator_llm() -> BaseChatModel:
    """Narrator: secondary tier, temperature=0.3 (natural expression)."""
    return get_secondary_llm(temperature=0.3)


def get_knowledge_llm() -> BaseChatModel:
    """Knowledge QA: secondary tier, temperature=0.5 (conversational)."""
    return get_secondary_llm(temperature=0.5)


def get_report_llm() -> BaseChatModel:
    """Report generator: primary tier, temperature=0.3 (structured writing)."""
    return get_primary_llm(temperature=0.3)


def get_report_eval_llm() -> BaseChatModel:
    """Report evaluator (Reflection): primary tier, temperature=0.1."""
    return get_primary_llm(temperature=0.1)


def get_query_rewriter_llm() -> BaseChatModel:
    """Query rewriter for RAG: secondary tier, temperature=0.1."""
    return get_secondary_llm(temperature=0.1)


def get_data_collector_llm() -> BaseChatModel:
    """Data collector (tool calling): primary tier, temperature=0.0."""
    return get_primary_llm(temperature=0.0)


def get_batch_llm() -> BaseChatModel:
    """Batch aggregation: primary with fallback, temperature=0.1.

    Returns BaseChatModel (may be ChatOpenAI when primary uses the
    Bailian API provider — [P0-D] fixed the stale ChatOllama annotation).
    """
    return get_llm_with_fallback(temperature=0.1)


# =============================================================================
# Embedding Model [v7.1: Ollama-based]
# =============================================================================

_embedding_instance: OllamaEmbeddings | None = None


def get_embedding_model() -> OllamaEmbeddings:
    """
    Get Ollama embedding model (bge-large or nomic-embed-text).

    Lazy-initialized singleton to avoid loading at import time.
    """
    global _embedding_instance
    if _embedding_instance is None:
        _embedding_instance = OllamaEmbeddings(
            model=EMBEDDING_MODEL,
            base_url=OLLAMA_BASE_URL,
        )
        logger.info(f"[Embedding] Initialized Ollama embedding: {EMBEDDING_MODEL}")
    return _embedding_instance
