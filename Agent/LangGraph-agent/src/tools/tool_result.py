"""
ToolResult — 结构化工具返回类型 [P1-A].

所有工具不再返回纯字符串，而是返回结构化的 ToolResult 对象：
- status: success/error
- data: 解析后的 dict（方便 LLM 理解，节省 token）
- raw: 原始字符串（用于日志和调试）
- error: 错误信息（如果 status=error）
- latency_ms: 执行延迟

【改进点】
  旧方案: 所有工具返回 str(JSON)，LLM 需要自己解析
  新方案: 工具返回结构化对象，系统自动解析，LLM 直接使用 dict

【面试知识点】
  Q: 为什么用结构化返回？
  A: 结构化返回的好处：
     1. LLM 节省 token（不需要解析 JSON 字符串）
     2. 错误处理更明确（status 字段直接表示成败）
     3. 便于监控和审计（latency_ms 追踪性能）
     4. 支持类型安全（Pydantic 模型验证）
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """结构化工具返回结果 [P1-A]."""

    status: str = Field(
        default="success",
        description="执行状态: success / error / degraded",
    )
    tool_name: str = Field(default="", description="工具名称")
    data: Optional[dict[str, Any]] = Field(default=None, description="解析后的结构化数据")
    raw: str = Field(default="", description="原始字符串（用于日志）")
    error: Optional[str] = Field(default=None, description="错误信息")
    latency_ms: float = Field(default=0.0, description="执行延迟（毫秒）")
    metadata: dict[str, Any] = Field(default_factory=dict, description="额外元数据")

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def is_error(self) -> bool:
        return self.status == "error"

    @property
    def is_degraded(self) -> bool:
        return self.status == "degraded"

    def to_llm_text(self) -> str:
        """生成 LLM 友好的文本描述."""
        if self.is_error:
            return f"[错误] {self.tool_name}: {self.error or '未知错误'}"

        if self.is_degraded:
            return f"[降级] {self.tool_name}: {self.error or '部分失败'}"

        parts = [f"[{self.tool_name}] 成功"]
        if self.data:
            parts.append(json.dumps(self.data, ensure_ascii=False, indent=2))
        return "\n".join(parts)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def create_success(
        cls,
        tool_name: str,
        data: Optional[dict] = None,
        raw: str = "",
        latency_ms: float = 0.0,
    ) -> ToolResult:
        """创建成功结果."""
        return cls(
            status="success",
            tool_name=tool_name,
            data=data,
            raw=raw,
            latency_ms=latency_ms,
        )

    @classmethod
    def create_error(
        cls,
        tool_name: str,
        error_msg: str,
        raw: str = "",
        latency_ms: float = 0.0,
    ) -> ToolResult:
        """创建错误结果."""
        return cls(
            status="error",
            tool_name=tool_name,
            error=error_msg,
            raw=raw,
            latency_ms=latency_ms,
        )

    @classmethod
    def create_degraded(
        cls,
        tool_name: str,
        data: Optional[dict] = None,
        error_msg: str = "",
        raw: str = "",
        latency_ms: float = 0.0,
    ) -> ToolResult:
        """创建降级结果."""
        return cls(
            status="degraded",
            tool_name=tool_name,
            data=data,
            error=error_msg,
            raw=raw,
            latency_ms=latency_ms,
        )


# =============================================================================
# 工具执行包装器
# =============================================================================


class ToolExecutor:
    """工具执行器 —— 统一的同步/异步工具调用封装 [P1-A].

    功能：
    1. 自动计时（latency_ms）
    2. 异常捕获 → ToolResult.error
    3. 自动 JSON 解析 → ToolResult.data
    4. Circuit Breaker 检查

    使用方式：
        executor = ToolExecutor()
        result = await executor.run(fiber_performance_query, {"fiber_id": "5"})
        if result.is_success:
            print(result.data)
    """

    def __init__(self, circuit_breaker=None):
        self._circuit_breaker = circuit_breaker

    async def run(
        self,
        tool_fn,
        params: dict,
        tool_name: str = "",
        timeout: float = 30.0,
    ) -> ToolResult:
        """执行工具函数，返回结构化结果.

        Args:
            tool_fn: 工具函数（async 或 sync）
            params: 参数字典
            tool_name: 工具名称（用于结果标记）
            timeout: 超时时间（秒）

        Returns:
            ToolResult
        """
        start = time.time()
        effective_name = tool_name or getattr(tool_fn, "name", "unknown")

        # 熔断器检查
        if self._circuit_breaker and self._circuit_breaker.is_open(effective_name):
            return ToolResult.create_error(
                tool_name=effective_name,
                error_msg="Circuit breaker open",
                latency_ms=0.0,
            )

        try:
            # 调用工具（支持 async 和 sync）
            import asyncio

            if asyncio.iscoroutinefunction(tool_fn):
                raw = await asyncio.wait_for(tool_fn.ainvoke(params), timeout=timeout)
            else:
                raw = tool_fn.invoke(params)

            latency_ms = (time.time() - start) * 1000

            # 尝试解析 JSON
            data = None
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                    data = parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    pass
            elif isinstance(raw, dict):
                data = raw

            return ToolResult.create_success(
                tool_name=effective_name,
                data=data,
                raw=str(raw),
                latency_ms=latency_ms,
            )

        except asyncio.TimeoutError:
            latency_ms = (time.time() - start) * 1000
            # 超时是可重试的临时故障 → degraded（区分于 error：可部分降级/换渠道）
            return ToolResult.create_degraded(
                tool_name=effective_name,
                error_msg=f"Timeout after {timeout}s",
                latency_ms=latency_ms,
            )
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            return ToolResult.create_error(
                tool_name=effective_name,
                error_msg=str(e),
                latency_ms=latency_ms,
            )


# =============================================================================
# 全局实例
# =============================================================================

_executor_instance: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """获取全局 ToolExecutor 单例."""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = ToolExecutor()
    return _executor_instance
