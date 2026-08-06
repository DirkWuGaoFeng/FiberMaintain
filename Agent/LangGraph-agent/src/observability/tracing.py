"""
Observability: LangFuse Tracing integration [v7.1].

Provides the "Tracing" pillar of the three-pillar observability model:
  - Tracing (LangFuse): full conversation trace (intent → params → tools → loop → output)
  - Metrics (Prometheus): see metrics.py
  - Audit (JSONL): see audit.py

LangFuse is activated only when LANGFUSE_PUBLIC_KEY is set in environment.
When unavailable, this module is a no-op (zero overhead).

Usage:
    from src.observability.tracing import get_langfuse_handler
    handler = get_langfuse_handler()  # None if not configured
"""

from __future__ import annotations

import logging
from typing import Optional

from ..config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

logger = logging.getLogger(__name__)

_handler_instance = None
_init_attempted = False


def get_langfuse_handler():
    """
    Get the LangFuse callback handler for LangChain/LangGraph tracing.

    Returns:
        CallbackHandler instance if LangFuse is configured and available,
        None otherwise (graceful degradation).
    """
    global _handler_instance, _init_attempted

    if _init_attempted:
        return _handler_instance

    _init_attempted = True

    # Skip if not configured
    if not LANGFUSE_PUBLIC_KEY or not LANGFUSE_SECRET_KEY:
        logger.debug("[Tracing] LangFuse not configured, skipping")
        return None

    try:
        from langfuse.callback import CallbackHandler

        _handler_instance = CallbackHandler(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            host=LANGFUSE_HOST,
        )
        logger.info(f"[Tracing] LangFuse initialized (host={LANGFUSE_HOST})")
        return _handler_instance

    except ImportError:
        logger.warning(
            "[Tracing] langfuse package not installed. "
            "Install with: pip install langfuse"
        )
        return None
    except Exception as e:
        logger.warning(f"[Tracing] LangFuse init failed: {e}")
        return None


def is_tracing_enabled() -> bool:
    """Check if LangFuse tracing is active."""
    return get_langfuse_handler() is not None
