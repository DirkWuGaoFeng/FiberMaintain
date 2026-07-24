"""LLM 客户端：OLLAMA（OpenAI 兼容）+ 降级/熔断集成 + Token 统计。"""
from __future__ import annotations
import logging, time
from typing import Any, AsyncIterator

from openai import AsyncOpenAI, APIError, APITimeoutError

from src.settings import settings
from src.monitoring.metrics import LLM_TOKENS, LLM_LATENCY

logger = logging.getLogger("fiber.llm")

class ModelCircuitOpen(Exception):
    """模型熔断，暂不可用。"""

class LLMClient:
    def __init__(self, degradation_mw) -> None:
        cfg = settings.llm
        self._client = AsyncOpenAI(base_url=cfg["base_url"],
                                   api_key=cfg.get("api_key", "ollama"))
        self.model = cfg["model"]
        self.mw = degradation_mw      # ModelDegradationMiddleware

    async def chat(self, messages: list[dict],
                   tools: list[dict] | None = None,
                   stream: bool = False) -> Any:
        if self.mw.circuit_open:
            raise ModelCircuitOpen("模型服务熔断中，请稍后重试")

        params = self.mw.profile_params()
        profile = self.mw.current_profile()
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": params["temperature"],
            "max_tokens": params["max_tokens"],
            "stream": stream,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        started = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(**kwargs)
            self.mw.record_success()
            LLM_LATENCY.observe(time.perf_counter() - started)
            if not stream:
                self._count_tokens(resp)
            return resp
        except (APITimeoutError, APIError, Exception) as e:
            self.mw.record_failure()
            logger.warning("LLM 调用失败（profile=%s）: %s", profile, e)
            raise

    def _count_tokens(self, resp: Any) -> None:
        usage = getattr(resp, "usage", None)
        if usage:
            LLM_TOKENS.labels(direction="input").inc(usage.prompt_tokens or 0)
            LLM_TOKENS.labels(direction="output").inc(usage.completion_tokens or 0)


# 延迟初始化（避免循环导入）
llm: LLMClient | None = None

def init_llm(degradation_mw) -> LLMClient:
    global llm
    llm = LLMClient(degradation_mw)
    return llm