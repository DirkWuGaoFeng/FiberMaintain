"""
LLM provider configuration with fallback chain.

Implements the 4-level degradation:
  L1: Primary model (qwen2.5:7b) - normal operation
  L2: Fallback models (7b -> 3b -> 1.5b) via with_fallbacks
  L3: Rule-based templates (no LLM)
  L4: Pure RAG mode (no LLM, only knowledge base)
"""

from __future__ import annotations

import logging
import os

from langchain_ollama import ChatOllama

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
LLM_PRIMARY = os.environ.get("LLM_PRIMARY", "qwen2.5:7b")
LLM_FALLBACK = os.environ.get("LLM_FALLBACK", "qwen2.5:3b")
LLM_FAST = os.environ.get("LLM_FAST", "qwen2.5:1.5b")


# =============================================================================
# Model Instances
# =============================================================================

def get_primary_llm(temperature: float = 0.1):
    """Get primary LLM with deterministic settings (P4: deterministic priority)."""
    return ChatOllama(
        model=LLM_PRIMARY,
        temperature=temperature,
        base_url=OLLAMA_BASE_URL,
        seed=42,
        num_ctx=8192,
    )


def get_fallback_llm(temperature: float = 0.1):
    """Get fallback LLM (3b model)."""
    return ChatOllama(
        model=LLM_FALLBACK,
        temperature=temperature,
        base_url=OLLAMA_BASE_URL,
        seed=42,
    )


def get_fast_llm(temperature: float = 0.1):
    """Get fast LLM (1.5b model) for last-resort fallback."""
    return ChatOllama(
        model=LLM_FAST,
        temperature=temperature,
        base_url=OLLAMA_BASE_URL,
        seed=42,
    )


def get_llm_with_fallback(temperature: float = 0.1):
    """
    Get LLM with full fallback chain (L2 degradation).

    Chain: qwen2.5:7b -> qwen2.5:3b -> qwen2.5:1.5b
    Triggers on: TimeoutException, ConnectError
    """
    import httpx

    primary = get_primary_llm(temperature)
    fallback = get_fallback_llm(temperature)
    fast = get_fast_llm(temperature)

    return primary.with_fallbacks(
        [fallback, fast],
        exceptions_to_handle=(httpx.TimeoutException, httpx.ConnectError, Exception),
    )


# =============================================================================
# Specialized LLM Instances (per Sub-Agent temperature)
# =============================================================================

def get_intent_llm():
    """Intent classifier LLM: temperature=0.0 (maximum determinism)."""
    return get_primary_llm(temperature=0.0)


def get_data_collector_llm():
    """Data collector LLM: temperature=0.0 (tool calling accuracy)."""
    return get_primary_llm(temperature=0.0)


def get_analysis_llm():
    """Analysis expert LLM: temperature=0.1 (slight creativity for analysis)."""
    return get_llm_with_fallback(temperature=0.1)


def get_report_llm():
    """Report generator LLM: temperature=0.3 (creative writing)."""
    return get_llm_with_fallback(temperature=0.3)


def get_knowledge_llm():
    """Knowledge assistant LLM: temperature=0.5 (conversational)."""
    return get_llm_with_fallback(temperature=0.5)


def get_batch_llm():
    """Batch processor LLM: temperature=0.1 (deterministic aggregation)."""
    return get_llm_with_fallback(temperature=0.1)
