"""
Collection Agent — 数据采集层.

职责：根据 ExecutionPlan.tools 调用后端 API 获取数据。
双模式：
- 确定性路径：match_type="rule" + 参数完整 → 直调 HTTP API，零 LLM，<500ms
- ReAct 路径：参数不完整或 match_type="llm" → 3b LLM 工具编排

约束：
- 只使用 plan.tools 中声明的工具（Bounded ReAct）
- 不做分析判断
- 返回结构化 CollectionPayload
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from ...llm.provider import get_data_collector_llm
from ...tools import DATA_COLLECTOR_TOOLS
from ..contracts import (
    CollectionPayload,
    ConnectionInfo,
    FiberMetrics,
    ToolCallRecord,
)
from ..models import AgentLayer, AgentResult, ExecutionPlan
from ..streaming import StreamEmitter, StreamEventType
from .base import BaseAgent

logger = logging.getLogger(__name__)

# 工具名 → 工具对象 的映射
_TOOL_MAP = {t.name: t for t in DATA_COLLECTOR_TOOLS}

COLLECTION_SYSTEM = """你是光纤维护系统的数据采集员。
你的唯一职责是调用工具获取光纤数据，不做分析判断。

## 规则
1. 只使用指定的工具列表中的工具
2. 光纤 ID 为整数，直接使用
3. 获取所有相关数据
4. 如果某个查询失败，报告错误但继续其他查询
5. 最终输出 JSON 格式的数据摘要
6. 不要编造数据，不要做分析判断

## 可用工具
{tools_list}

## 输出格式
{{"collected": [{{"tool": "工具名", "params": {{}}, "result_summary": "关键数据"}}], "errors": [...]}}
"""


class CollectionAgent(BaseAgent):
    """数据采集 Agent — 确定性优先 + Bounded ReAct 兜底."""

    @property
    def layer(self) -> AgentLayer:
        return AgentLayer.COLLECTION

    async def execute(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any],
    ) -> AgentResult:
        # 判断是否可以走确定性路径
        if self._can_use_deterministic(plan, context):
            return await self._deterministic_collect(plan, context)
        else:
            return await self._react_collect(plan, context)

    def _can_use_deterministic(
        self, plan: ExecutionPlan, context: dict
    ) -> bool:
        """判断是否满足确定性路径条件."""
        # 条件：规则命中 + 有 fiber_ids 参数 + 工具列表非空
        if plan.match_type != "rule":
            return False
        params = context.get("normalized_params", {})
        if not params.get("fiber_ids"):
            return False
        if not plan.tools:
            return False
        # 补充采集走 ReAct（因为需要 LLM 判断调什么）
        if context.get("additional_query"):
            return False
        return True

    # =========================================================================
    # 确定性路径：零 LLM，直调 API
    # =========================================================================

    async def _deterministic_collect(
        self, plan: ExecutionPlan, context: dict
    ) -> AgentResult:
        """确定性数据采集：直接调用工具函数，解析 JSON 响应."""
        trace_id = context.get("trace_id", "")
        params = context.get("normalized_params", {})
        fiber_ids = params.get("fiber_ids", [])
        emitter: StreamEmitter | None = context.get("emitter")
        start = time.time()

        logger.info(
            f"[TRACE:{trace_id}] [CollectionAgent] Deterministic path: "
            f"fibers={fiber_ids} tools={plan.tools}"
        )

        # 流式事件：开始采集
        if emitter:
            await emitter.emit(
                StreamEventType.COLLECTION_START,
                f"开始采集 {len(fiber_ids)} 条光纤数据...",
                {"fiber_count": len(fiber_ids), "tools": plan.tools},
            )

        all_metrics: list[FiberMetrics] = []
        all_connections: list[ConnectionInfo] = []
        tool_calls: list[ToolCallRecord] = []

        for fiber_id in fiber_ids:
            metrics = FiberMetrics(fiber_id=int(fiber_id))

            for tool_name in plan.tools:
                tool_fn = _TOOL_MAP.get(tool_name)
                if not tool_fn:
                    continue

                call_start = time.time()
                try:
                    # 直接调用工具函数（绕过 LLM）
                    raw_result = await tool_fn.ainvoke(
                        {"fiber_id": str(fiber_id)}
                    )
                    latency = round((time.time() - call_start) * 1000, 2)
                    tool_calls.append(ToolCallRecord(
                        tool_name=tool_name,
                        params={"fiber_id": str(fiber_id)},
                        success=True,
                        latency_ms=latency,
                    ))

                    # 解析 JSON 响应 → 结构化字段
                    self._parse_tool_response(
                        tool_name, raw_result, metrics
                    )

                    # 流式事件：工具完成
                    if emitter:
                        await emitter.emit(
                            StreamEventType.TOOL_COMPLETE,
                            f"已获取 {tool_name} 数据 ✓",
                            {"tool": tool_name, "fiber_id": fiber_id},
                        )

                except Exception as e:
                    latency = round((time.time() - call_start) * 1000, 2)
                    tool_calls.append(ToolCallRecord(
                        tool_name=tool_name,
                        params={"fiber_id": str(fiber_id)},
                        success=False,
                        error=str(e),
                        latency_ms=latency,
                    ))
                    logger.warning(
                        f"[TRACE:{trace_id}] [CollectionAgent] "
                        f"Tool {tool_name} failed: {e}"
                    )

                    # 流式事件：工具失败
                    if emitter:
                        await emitter.emit(
                            StreamEventType.TOOL_ERROR,
                            f"{tool_name} 查询失败",
                            {"tool": tool_name, "error": str(e)},
                        )

            all_metrics.append(metrics)

        elapsed = round((time.time() - start) * 1000, 2)
        payload = CollectionPayload(
            metrics=all_metrics,
            connections=all_connections,
            tool_calls=tool_calls,
            collection_mode="deterministic",
        )

        # 流式事件：采集完成
        if emitter:
            await emitter.emit(
                StreamEventType.COLLECTION_DONE,
                f"数据采集完成 ({elapsed}ms)",
                {"elapsed_ms": elapsed, "fiber_count": len(all_metrics)},
            )

        logger.info(
            f"[TRACE:{trace_id}] [CollectionAgent] Deterministic done "
            f"{elapsed}ms, {len(all_metrics)} fibers, "
            f"{len(tool_calls)} calls"
        )

        return AgentResult(
            layer=self.layer,
            success=True,
            data=payload.model_dump(),
            llm_calls=0,  # 零 LLM 调用
            latency_ms=elapsed,
        )

    def _parse_tool_response(
        self, tool_name: str, raw_result: str, metrics: FiberMetrics
    ) -> None:
        """将工具 JSON 响应解析到 FiberMetrics 字段."""
        try:
            data = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        except (json.JSONDecodeError, TypeError):
            return

        if not isinstance(data, dict):
            return

        if "spanloss" in tool_name:
            # {"fiber_id": 1, "spanloss": 3.5}
            val = data.get("spanloss")
            if val is not None:
                metrics.spanloss_db = float(val)

        elif "performance" in tool_name:
            # {"fiber_id": 1, "src_oop": -5.2, "dst_iop": -8.1}
            if data.get("src_oop") is not None:
                metrics.oop_dbm = float(data["src_oop"])
            if data.get("dst_iop") is not None:
                metrics.iop_dbm = float(data["dst_iop"])

    # =========================================================================
    # ReAct 路径：LLM 工具编排（参数不完整 / LLM 分类场景）
    # =========================================================================

    async def _react_collect(
        self, plan: ExecutionPlan, context: dict
    ) -> AgentResult:
        """ReAct 数据采集：LLM 决定工具调用顺序."""
        from langgraph.prebuilt import create_react_agent

        trace_id = context.get("trace_id", "")

        # Bounded: 只使用 plan 声明的工具
        allowed_tools = self._resolve_tools(plan.tools)
        if not allowed_tools:
            allowed_tools = DATA_COLLECTOR_TOOLS  # fallback 全量

        # 构建 prompt
        prompt = self._build_prompt(plan, context)
        tools_list = ", ".join(t.name for t in allowed_tools)
        system = COLLECTION_SYSTEM.format(tools_list=tools_list)

        # ReAct Agent
        llm = get_data_collector_llm()
        agent = create_react_agent(
            model=llm,
            tools=allowed_tools,
            prompt=system,
        )

        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config={"recursion_limit": 10},
        )

        # 提取结果
        messages = result.get("messages", [])
        data_summary = ""
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                data_summary = msg.content
                break

        if not data_summary:
            return AgentResult(
                layer=self.layer,
                success=False,
                error="数据采集未返回有效结果",
            )

        # 截断保护
        if len(data_summary) > 3000:
            data_summary = data_summary[:3000] + "\n...(截断)"

        # ReAct 路径返回 raw_summary（供 Analysis regex fallback）
        payload = CollectionPayload(
            raw_summary=data_summary,
            collection_mode="react",
        )

        return AgentResult(
            layer=self.layer,
            success=True,
            data=payload.model_dump(),
            llm_calls=1,
        )

    def _resolve_tools(self, tool_names: list[str]) -> list:
        """将工具名列表解析为工具对象."""
        resolved = []
        for name in tool_names:
            if name in _TOOL_MAP:
                resolved.append(_TOOL_MAP[name])
            else:
                logger.warning(f"[CollectionAgent] Unknown tool: {name}")
        return resolved

    def _build_prompt(self, plan: ExecutionPlan, context: dict) -> str:
        """构建采集 prompt."""
        parts = []

        # 补充采集信号
        additional = context.get("additional_query")
        if additional:
            parts.append(f"## 补充采集（第 {context.get('loop_round', 1)} 轮）")
            parts.append(f"原因：{additional.get('reason', '')}")
            if additional.get("tool"):
                parts.append(f"建议工具：{additional['tool']}")

        # 用户请求
        user_input = context.get("user_input", "")
        if user_input:
            parts.append(f"## 用户请求\n{user_input}")

        # 参数
        params = context.get("normalized_params", {})
        if params:
            parts.append(f"## 参数\n{json.dumps(params, ensure_ascii=False)}")

        parts.append("\n请调用工具获取数据。")
        return "\n\n".join(parts)
