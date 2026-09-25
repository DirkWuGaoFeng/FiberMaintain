"""
可观测性：LangFuse 追踪集成 [v7.1]。

提供三支柱可观测性模型中的 "Tracing（追踪）" 支柱：
  - 追踪（LangFuse）：完整会话 trace（意图 → 参数 → 工具 → 循环 → 输出）
  - 指标（Prometheus）：参见 metrics.py
  - 审计（JSONL）：参见 audit.py

仅当环境中设置了 LANGFUSE_PUBLIC_KEY 时才启用 LangFuse。
当其不可用时，本模块为空操作（零开销）。

用法：
    from src.observability.tracing import get_langfuse_handler
    handler = get_langfuse_handler()  # 未配置时返回 None
"""

from __future__ import annotations

import logging

from ..config import LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

logger = logging.getLogger(__name__)

_handler_instance = None
_init_attempted = False


def get_langfuse_handler():
    """
    获取用于 LangChain/LangGraph 追踪的 LangFuse 回调处理器。

    Returns:
        LangFuse 已配置且可用时返回 CallbackHandler 实例，
        否则返回 None（优雅降级）。
    """
    global _handler_instance, _init_attempted

    if _init_attempted:
        return _handler_instance

    _init_attempted = True

    # 未配置则跳过
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
        logger.warning("[Tracing] langfuse package not installed. " "Install with: pip install langfuse")
        return None
    except Exception as e:
        logger.warning(f"[Tracing] LangFuse init failed: {e}")
        return None


def is_tracing_enabled() -> bool:
    """检查 LangFuse 追踪是否已启用。"""
    return get_langfuse_handler() is not None
