"""
Tracing callback: records full-chain spans for observability.
"""

from __future__ import annotations

import logging
import time

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class TracingCallback(BaseCallbackHandler):
    """Tracing callback: records timing and metadata for all chain/LLM/tool calls."""

    def __init__(self):
        self._spans: dict[str, float] = {}

    def on_chain_start(self, serialized: dict, inputs: dict, **kwargs) -> None:
        name = serialized.get("name", "unknown_chain")
        self._spans[name] = time.monotonic()
        logger.debug(f"[Trace] Chain start: {name}")

    def on_chain_end(self, outputs: dict, **kwargs) -> None:
        name = kwargs.get("name", "unknown_chain")
        start = self._spans.pop(name, time.monotonic())
        elapsed = time.monotonic() - start
        logger.debug(f"[Trace] Chain end: {name} ({elapsed:.2f}s)")

    def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs) -> None:
        model = serialized.get("model", serialized.get("name", "unknown_llm"))
        self._spans[f"llm_{model}"] = time.monotonic()
        logger.debug(f"[Trace] LLM start: {model}")

    def on_llm_end(self, response, **kwargs) -> None:
        model = "unknown_llm"
        key = f"llm_{model}"
        start = self._spans.pop(key, time.monotonic())
        elapsed = time.monotonic() - start
        logger.debug(f"[Trace] LLM end: {model} ({elapsed:.2f}s)")

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs) -> None:
        name = serialized.get("name", "unknown_tool")
        self._spans[f"tool_{name}"] = time.monotonic()
        logger.debug(f"[Trace] Tool start: {name}")

    def on_tool_end(self, output: str, **kwargs) -> None:
        name = kwargs.get("name", "unknown_tool")
        key = f"tool_{name}"
        start = self._spans.pop(key, time.monotonic())
        elapsed = time.monotonic() - start
        logger.debug(f"[Trace] Tool end: {name} ({elapsed:.2f}s)")

    def on_llm_error(self, error: Exception, **kwargs) -> None:
        logger.error(f"[Trace] LLM error: {error}")

    def on_tool_error(self, error: Exception, **kwargs) -> None:
        logger.error(f"[Trace] Tool error: {error}")
