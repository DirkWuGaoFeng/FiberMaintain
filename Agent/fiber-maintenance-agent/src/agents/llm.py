"""LLM 客户端：多 Provider 抽象层 + 降级/熔断集成 + Token 统计。

支持 Provider：
- ollama:           Ollama 原生 /api/chat（支持 think=false 禁用思维链）
- openai_compatible: OpenAI 兼容 API（KIMI / DeepSeek / 通义千问等）

通过 config.yaml 的 llm.provider 字段切换，无需修改业务代码。
"""
from __future__ import annotations
import asyncio, json, logging, time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from src.settings import settings
from src.monitoring.metrics import LLM_TOKENS, LLM_LATENCY

logger = logging.getLogger("fiber.llm")


# ══════════════════════════════════════════════════════════
#  内部统一响应格式（OpenAI 兼容）
# ══════════════════════════════════════════════════════════

@dataclass
class _FuncCall:
    """模拟 OpenAI tool_call.function"""
    name: str
    arguments: str

@dataclass
class _ToolCall:
    """模拟 OpenAI tool_call"""
    id: str
    type: str = "function"
    function: _FuncCall = None
    index: int = 0

@dataclass
class _Message:
    """模拟 OpenAI message"""
    content: str = ""
    tool_calls: list[_ToolCall] | None = None
    role: str = "assistant"
    thinking: str | None = None

    def model_dump(self, exclude_none=True):
        d = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": tc.type,
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in self.tool_calls
            ]
        if self.thinking and not exclude_none:
            d["thinking"] = self.thinking
        return d

@dataclass
class _Choice:
    message: _Message
    index: int = 0
    finish_reason: str = "stop"

@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

@dataclass
class _ChatResp:
    """模拟 OpenAI ChatCompletion 响应"""
    choices: list[_Choice]
    usage: _Usage = field(default_factory=_Usage)
    id: str = ""
    model: str = ""


# ── 流式 chunk 包装 ─────────────────────────────────────────
@dataclass
class _StreamDelta:
    content: str | None = None
    tool_calls: list | None = None

@dataclass
class _StreamChoice:
    delta: _StreamDelta
    index: int = 0
    finish_reason: str | None = None

@dataclass
class _StreamChunk:
    choices: list[_StreamChoice]


class ModelCircuitOpen(Exception):
    """模型熔断，暂不可用。"""


# ══════════════════════════════════════════════════════════
#  Provider 抽象基类
# ═══════════════════════════════════════════════════════════

class BaseProvider(ABC):
    """LLM Provider 抽象基类。

    所有 Provider 必须实现 chat() 和 stream_request()，
    返回统一的 _ChatResp / _StreamChunk 格式。
    """

    def __init__(self, cfg: dict) -> None:
        self._cfg = cfg
        self.model = cfg["model"]
        self.api_key = cfg.get("api_key", "")
        self.base_url = cfg.get("base_url", "")
        self._disable_think = cfg.get("disable_think", False)
        self._client: httpx.AsyncClient | None = None

    def switch_model(self, model_name: str) -> None:
        """运行时切换模型（降级/恢复时调用）。"""
        if model_name != self.model:
            logger.info("Provider 模型切换: %s → %s", self.model, model_name)
            self.model = model_name
            # 关闭旧连接，下次请求重建
            if self._client and not self._client.is_closed:
                # 不立即关闭，由 _get_client 重建
                pass

    async def _get_client(self, timeout: float = 180.0) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                timeout=httpx.Timeout(timeout, connect=10.0),
                headers=headers,
            )
        return self._client

    @abstractmethod
    async def chat(self, messages: list[dict],
                   tools: list[dict] | None = None,
                   stream: bool = False,
                   temperature: float | None = None,
                   top_p: float | None = None,
                   max_tokens: int = 4096) -> Any:
        """非流式聊天，返回 _ChatResp。"""
        ...

    @abstractmethod
    def stream_request(self, client: httpx.AsyncClient,
                       body: dict, started: float) -> AsyncIterator[_StreamChunk]:
        """流式请求，yield _StreamChunk。"""
        ...

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ══════════════════════════════════════════════════════════
#  Ollama Provider（原生 /api/chat）
# ═══════════════════════════════════════════════════════════

def _to_ollama_messages(messages: list[dict]) -> list[dict]:
    """将 OpenAI 格式的 messages 转为 Ollama 原生格式。

    差异点：
    - assistant 消息的 tool_calls：去掉 id/type，保留 {function: {name, arguments}}
    - arguments 从 JSON 字符串转为 dict
    """
    result = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "assistant" and msg.get("tool_calls"):
            ollama_tcs = []
            for tc in msg["tool_calls"]:
                func = tc.get("function", tc)
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                ollama_tcs.append({
                    "function": {
                        "name": func.get("name", ""),
                        "arguments": args
                    }
                })
            result.append({
                "role": "assistant",
                "content": msg.get("content", "") or "",
                "tool_calls": ollama_tcs,
            })
        else:
            result.append(msg)
    return result


def _parse_ollama_response(data: dict) -> _ChatResp:
    """将 Ollama /api/chat 响应转为内部统一格式"""
    msg = data.get("message", {})
    content = msg.get("content", "")
    thinking = msg.get("thinking")

    tool_calls = None
    if msg.get("tool_calls"):
        tool_calls = []
        for i, tc in enumerate(msg["tool_calls"]):
            func = tc.get("function", {})
            tool_calls.append(_ToolCall(
                id=f"call_{i}_{hash(func.get('name',''))}",
                function=_FuncCall(
                    name=func.get("name", ""),
                    arguments=json.dumps(func.get("arguments", {}),
                                         ensure_ascii=False),
                ),
                index=i,
            ))

    ollama_msg = _Message(
        content=content,
        tool_calls=tool_calls,
        thinking=thinking,
    )

    usage = _Usage(
        prompt_tokens=data.get("prompt_eval_count", 0),
        completion_tokens=data.get("eval_count", 0),
        total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
    )

    return _ChatResp(
        choices=[_Choice(message=ollama_msg)],
        usage=usage,
        model=data.get("model", ""),
    )


class OllamaProvider(BaseProvider):
    """Ollama 原生 API Provider（/api/chat）。

    特点：
    - 支持 think=false 禁用 qwen3 思维链
    - 使用 options.num_predict 控制最大输出 token
    - 流式响应中 tool_calls 在最后一个 chunk 一次性给出
    """

    def __init__(self, cfg: dict) -> None:
        super().__init__(cfg)
        # 从 OpenAI base_url 提取 Ollama 原生地址
        # config: http://localhost:11434/v1 → http://localhost:11434
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.base_url = base

    async def chat(self, messages: list[dict],
                   tools: list[dict] | None = None,
                   stream: bool = False,
                   temperature: float | None = None,
                   top_p: float | None = None,
                   max_tokens: int = 4096) -> _ChatResp:
        body: dict = {
            "model": self.model,
            "messages": _to_ollama_messages(messages),
            "stream": stream,
            "options": {
                "temperature": temperature or 0.3,
                "num_predict": max_tokens,
            },
        }
        if top_p is not None:
            body["options"]["top_p"] = top_p
        if tools:
            body["tools"] = tools
        if self._disable_think:
            body["think"] = False

        client = await self._get_client()
        resp = await client.post("/api/chat", json=body)
        resp.raise_for_status()
        return _parse_ollama_response(resp.json())

    async def stream_request(self, client: httpx.AsyncClient,
                              body: dict, started: float) -> AsyncIterator[_StreamChunk]:
        """Ollama 流式请求，逐 chunk yield 统一格式。

        LLMClient 传入的 body 是 OpenAI 格式（temperature/max_tokens 在顶层），
        这里需要转为 Ollama 原生格式（放入 options，max_tokens→num_predict）。
        """
        # ── 格式转换：OpenAI → Ollama ──
        temperature = body.pop("temperature", 0.3)
        max_tokens = body.pop("max_tokens", 4096)
        top_p = body.pop("top_p", None)
        messages = body.pop("messages", [])

        ollama_body: dict = {
            "model": body.get("model", self.model),
            "messages": _to_ollama_messages(messages),
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if top_p is not None:
            ollama_body["options"]["top_p"] = top_p
        if body.get("tools"):
            ollama_body["tools"] = body["tools"]
        if self._disable_think:
            ollama_body["think"] = False

        async with client.stream("POST", "/api/chat", json=ollama_body) as resp:
            if resp.status_code >= 400:
                err_body = await resp.aread()
                logger.warning("Ollama 流式请求错误 status=%d resp=%s",
                               resp.status_code, err_body.decode()[:300])
            resp.raise_for_status()

            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg = data.get("message", {})
                content = msg.get("content")
                done = data.get("done", False)

                # Ollama 在最后一个 chunk 一次性给出 tool_calls，
                # 需拆成增量 delta 以兼容 OpenAI 流式格式
                if msg.get("tool_calls"):
                    for i, tc in enumerate(msg["tool_calls"]):
                        func = tc.get("function", {})
                        tc_id = f"call_{i}_{hash(func.get('name',''))}"
                        yield _StreamChunk(choices=[_StreamChoice(
                            delta=_StreamDelta(tool_calls=[_ToolCall(
                                id=tc_id,
                                function=_FuncCall(name=func.get("name", ""),
                                                   arguments=""),
                                index=i,
                            )])
                        )])
                        args_str = json.dumps(func.get("arguments", {}),
                                              ensure_ascii=False)
                        yield _StreamChunk(choices=[_StreamChoice(
                            delta=_StreamDelta(tool_calls=[_ToolCall(
                                id="",
                                function=_FuncCall(name="",
                                                   arguments=args_str),
                                index=i,
                            )])
                        )])
                elif content:
                    yield _StreamChunk(choices=[_StreamChoice(
                        delta=_StreamDelta(content=content)
                    )])

                if done:
                    break


# ═══════════════════════════════════════════════════════════
#  OpenAI 兼容 Provider（/v1/chat/completions）
#  适用于 KIMI / DeepSeek / 通义千问 / Azure OpenAI 等
# ═══════════════════════════════════════════════════════════

def _parse_openai_response(data: dict) -> _ChatResp:
    """将 OpenAI /v1/chat/completions 响应转为内部统一格式"""
    choices_data = data.get("choices", [])
    choices = []
    for c in choices_data:
        msg_data = c.get("message", {})
        content = msg_data.get("content", "")

        tool_calls = None
        if msg_data.get("tool_calls"):
            tool_calls = []
            for tc in msg_data["tool_calls"]:
                func = tc.get("function", {})
                tool_calls.append(_ToolCall(
                    id=tc.get("id", ""),
                    function=_FuncCall(
                        name=func.get("name", ""),
                        arguments=func.get("arguments", "{}"),
                    ),
                    index=tc.get("index", 0),
                ))

        choices.append(_Choice(
            message=_Message(content=content, tool_calls=tool_calls),
            index=c.get("index", 0),
            finish_reason=c.get("finish_reason", "stop"),
        ))

    usage_data = data.get("usage", {})
    usage = _Usage(
        prompt_tokens=usage_data.get("prompt_tokens", 0),
        completion_tokens=usage_data.get("completion_tokens", 0),
        total_tokens=usage_data.get("total_tokens", 0),
    )

    return _ChatResp(
        choices=choices,
        usage=usage,
        id=data.get("id", ""),
        model=data.get("model", ""),
    )


def _parse_openai_stream_chunk(data: dict) -> _StreamChunk | None:
    """解析 OpenAI SSE 流式 chunk，返回 _StreamChunk 或 None（done）"""
    choices_data = data.get("choices", [])
    if not choices_data:
        return None

    c = choices_data[0]
    delta = c.get("delta", {})
    finish_reason = c.get("finish_reason")

    content = delta.get("content")
    tool_calls_delta = delta.get("tool_calls")

    stream_tool_calls = None
    if tool_calls_delta:
        stream_tool_calls = []
        for tc in tool_calls_delta:
            func = tc.get("function", {})
            stream_tool_calls.append(_ToolCall(
                id=tc.get("id", ""),
                function=_FuncCall(
                    name=func.get("name", "") or "",
                    arguments=func.get("arguments", "") or "",
                ),
                index=tc.get("index", 0),
            ))

    return _StreamChunk(choices=[_StreamChoice(
        delta=_StreamDelta(content=content, tool_calls=stream_tool_calls),
        index=c.get("index", 0),
        finish_reason=finish_reason,
    )])


class OpenAICompatibleProvider(BaseProvider):
    """OpenAI 兼容 API Provider（/v1/chat/completions）。

    适用于：KIMI (moonshot)、DeepSeek、通义千问、Azure OpenAI 等
    所有遵循 OpenAI Chat Completions 格式的 API 服务。
    """

    async def chat(self, messages: list[dict],
                   tools: list[dict] | None = None,
                   stream: bool = False,
                   temperature: float | None = None,
                   top_p: float | None = None,
                   max_tokens: int = 4096) -> _ChatResp:
        body: dict = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature or 0.3,
            "max_tokens": max_tokens,
        }
        if top_p is not None:
            body["top_p"] = top_p
        if tools:
            body["tools"] = tools

        client = await self._get_client()
        resp = await client.post("/v1/chat/completions", json=body)
        resp.raise_for_status()
        return _parse_openai_response(resp.json())

    async def stream_request(self, client: httpx.AsyncClient,
                              body: dict, started: float) -> AsyncIterator[_StreamChunk]:
        """OpenAI SSE 流式请求"""
        body["stream"] = True

        async with client.stream("POST", "/v1/chat/completions", json=body) as resp:
            if resp.status_code >= 400:
                err_body = await resp.aread()
                logger.warning("OpenAI兼容 流式请求错误 status=%d resp=%s",
                               resp.status_code, err_body.decode()[:300])
            resp.raise_for_status()

            async for raw_line in resp.aiter_lines():
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("data: "):
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    chunk = _parse_openai_stream_chunk(data)
                    if chunk:
                        yield chunk


# ═══════════════════════════════════════════════════════════
#  Provider 工厂
# ═══════════════════════════════════════════════════════════

_PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    # 可扩展：添加更多 provider
    # "azure_openai": AzureOpenAIProvider,
    # "anthropic": AnthropicProvider,
}


def create_provider(cfg: dict) -> BaseProvider:
    """根据 config.yaml 的 llm.provider 字段创建对应 Provider。"""
    provider_name = cfg.get("provider", "ollama")
    provider_cls = _PROVIDER_REGISTRY.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"未知的 LLM provider: {provider_name}，"
            f"支持的 provider: {list(_PROVIDER_REGISTRY.keys())}"
        )
    logger.info("LLM Provider 初始化: %s (model=%s)", provider_name, cfg.get("model"))
    return provider_cls(cfg)


# ══════════════════════════════════════════════════════════
#  LLMClient（统一入口，集成降级/熔断/Token统计）
# ═══════════════════════════════════════════════════════════

class LLMClient:
    def __init__(self, degradation_mw) -> None:
        cfg = settings.llm
        self.mw = degradation_mw
        self._provider = create_provider(cfg)
        # 多模型配置：初始化时设置 primary 模型
        models_cfg = cfg.get("models", {})
        if models_cfg:
            primary_model = models_cfg.get("primary", cfg.get("model", ""))
            self._provider.switch_model(primary_model)
            logger.info("LLM 多模型模式: %s", models_cfg)
        self._context_window = cfg.get("context_window", 8192)
        self._default_timeout = cfg.get("default_timeout", 30)

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def provider_name(self) -> str:
        return type(self._provider).__name__

    @property
    def context_window(self) -> int:
        return self._context_window

    def sync_model_from_degradation(self) -> None:
        """从降级中间件同步当前模型名称（降级/恢复时调用）。"""
        models_cfg = settings.llm.get("models", {})
        if models_cfg:
            profile = self.mw.current_profile()
            target_model = models_cfg.get(profile, self._provider.model)
            if target_model != self._provider.model:
                self._provider.switch_model(target_model)

    def _switch_to_profile(self, profile: str) -> tuple[str, dict]:
        """切换到指定 profile 的模型，返回 (原模型名, 原profile参数) 用于恢复。"""
        models_cfg = settings.llm.get("models", {})
        target_model = models_cfg.get(profile, self._provider.model)
        original_model = self._provider.model
        if target_model != original_model:
            self._provider.switch_model(target_model)
        profile_params = settings.llm.get("profiles", {}).get(profile, {})
        return original_model, profile_params

    async def chat(self, messages: list[dict],
                   tools: list[dict] | None = None,
                   stream: bool = False,
                   temperature: float | None = None,
                   top_p: float | None = None,
                   model_profile: str | None = None) -> Any:
        """LLM 聊天调用。

        Args:
            model_profile: 指定模型 profile（如 'fast'/'primary'），
                           为 None 时使用降级中间件决定的 profile。
        """
        if self.mw.circuit_open:
            raise ModelCircuitOpen("模型服务熔断中，请稍后重试")

        # 若指定了 model_profile，临时切换到对应模型
        _original_model = None
        if model_profile:
            _original_model, _profile_params = self._switch_to_profile(model_profile)
            # 使用 profile 配置中的 temperature/max_tokens（调用方显式传入的优先）
            temp = temperature if temperature is not None else _profile_params.get("temperature", 0.3)
            max_tokens = _profile_params.get("max_tokens", 4096)
            profile = model_profile
        else:
            # 降级时同步切换模型
            self.sync_model_from_degradation()
            params = self.mw.profile_params()
            profile = self.mw.current_profile()
            temp = temperature if temperature is not None else params["temperature"]
            max_tokens = params["max_tokens"]

        started = time.perf_counter()
        max_retries = 2  # 服务端错误最多重试 2 次（切换模型）
        last_error = None

        try:
            return await self._chat_inner(
                messages, tools, stream, temp, top_p, max_tokens,
                profile, started, max_retries, model_profile)
        finally:
            # 恢复原始模型（仅在指定了 model_profile 时）
            if _original_model is not None and _original_model != self._provider.model:
                self._provider.switch_model(_original_model)

    async def _chat_inner(self, messages, tools, stream, temp, top_p,
                          max_tokens, profile, started, max_retries,
                          fixed_profile) -> Any:
        """内部聊天实现（不含 profile 切换逻辑）。"""
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if stream:
                    client = await self._provider._get_client()
                    return self._provider.stream_request(client, {
                        "model": self._provider.model,
                        "messages": messages,
                        "temperature": temp,
                        "max_tokens": max_tokens,
                        "top_p": top_p,
                        "tools": tools,
                    }, started)
                else:
                    result = await self._provider.chat(
                        messages=messages,
                        tools=tools,
                        stream=False,
                        temperature=temp,
                        top_p=top_p,
                        max_tokens=max_tokens,
                    )
                    self.mw.record_success()
                    LLM_LATENCY.observe(time.perf_counter() - started)
                    self._count_tokens(result)
                    return result

            except httpx.HTTPStatusError as e:
                status = e.response.status_code if e.response else 0
                resp_body = e.response.text[:500] if e.response else ""

                if 400 <= status < 500:
                    # ── 4xx 客户端错误：请求格式问题，降级无用 ──
                    logger.error(
                        "LLM 客户端错误 %d（provider=%s profile=%s），"
                        "不触发降级。resp=%s",
                        status, self.provider_name, profile, resp_body[:200])
                    raise  # 直接抛出，不重试、不计入降级

                # ── 5xx 服务端错误：触发降级 + 重试 ──
                self.mw.record_failure()
                last_error = e
                logger.warning(
                    "LLM 服务端错误 %d（provider=%s profile=%s attempt=%d/%d） resp=%s",
                    status, self.provider_name, profile,
                    attempt + 1, max_retries + 1, resp_body[:200])

                if attempt < max_retries:
                    # 指定了 fixed_profile 时不触发降级，保持当前模型重试
                    if not fixed_profile:
                        self.sync_model_from_degradation()
                        params = self.mw.profile_params()
                        temp = params["temperature"]
                        max_tokens = params["max_tokens"]
                    logger.info("LLM 重试：profile=%s model=%s",
                                profile, self.model)
                    continue
                raise

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                # ── 连接/超时：触发降级 + 重试 ──
                self.mw.record_failure()
                last_error = e
                logger.warning(
                    "LLM 连接失败（provider=%s profile=%s attempt=%d/%d）: %s",
                    self.provider_name, profile,
                    attempt + 1, max_retries + 1, e)

                if attempt < max_retries:
                    if not fixed_profile:
                        self.sync_model_from_degradation()
                        params = self.mw.profile_params()
                        temp = params["temperature"]
                        max_tokens = params["max_tokens"]
                    logger.info("LLM 重试：profile=%s model=%s",
                                profile, self.model)
                    continue
                raise

            except Exception as e:
                self.mw.record_failure()
                logger.warning("LLM 调用失败（provider=%s profile=%s）: %s",
                               self.provider_name, profile, e)
                raise

    def _count_tokens(self, resp: _ChatResp) -> None:
        if resp.usage:
            LLM_TOKENS.labels(direction="input").inc(resp.usage.prompt_tokens or 0)
            LLM_TOKENS.labels(direction="output").inc(resp.usage.completion_tokens or 0)

    async def close(self) -> None:
        await self._provider.close()


# ─ 延迟初始化 ──────────────────────────────────────────────
llm: LLMClient | None = None

def get_llm() -> LLMClient:
    """获取 LLM 客户端实例（运行时查找，避免循环导入问题）。"""
    if llm is None:
        raise RuntimeError("LLM 客户端未初始化，请先调用 init_llm()")
    return llm

def init_llm(degradation_mw) -> LLMClient:
    global llm
    llm = LLMClient(degradation_mw)
    return llm
