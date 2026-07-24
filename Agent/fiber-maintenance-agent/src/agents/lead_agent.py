"""Lead Agent 编排器：意图识别 → task 派遣 → 结果汇总（SSE 流式输出）。"""
from __future__ import annotations
import asyncio, json, logging, time
from typing import AsyncIterator

from src.settings import settings
from src.tools.registry import tool_schemas, execute_tool, tool
from src.agents.llm import llm, ModelCircuitOpen
from src.agents.scheduler import dispatch_subagent
from src.agents.sub_agents import SUBAGENTS
from src.middlewares import RunContext, build_chain
from src.memory.store import memory
from src.mcp import backend
from src.notify.notifier import notifier
from src.monitoring.metrics import (AGENT_REQUESTS, AGENT_REQUEST_DURATION,
                                    OFFLINE_MODE)

logger = logging.getLogger("fiber.lead")

LEAD_SYSTEM_PROMPT = """你是光纤维护服务系统的智能分析助手（Lead Agent）。

【核心职责】
1. 理解用户的光纤分析需求（单条分析/批量分析/趋势查询/巡检/知识问答/报告导出）
2. 通过 task 工具派遣合适的子智能体执行，再汇总结果
3. 生成结构化最终回复

【可用子智能体】（通过 task 工具派遣，agent 参数取以下名称）
- topology-analyst: 查询光纤连接、单盘、网元信息
- data-collector: 获取性能、告警、颜色、统计、趋势数据
- analysis-expert: 解读衰耗/颜色结果、异常检测、趋势分析、对比分析
- report-generator: 生成结构化报告、维护建议、文件导出（PDF/Excel/CSV）
- rag-retriever: 检索光纤领域知识库

【重要约束】
- 衰耗计算和颜色判定由后端 C++ 服务完成，你只调用 API 获取结果并解读
- 操作对象仅限网元间连纤（src_ne_id ≠ dst_ne_id）
- 批量分析：并行派遣，单条失败不影响其他，最终汇总成功/失败统计
- 单次批量查询最大 100 条
- 支持对比分析：同一光纤不同时间点 / 同网元对横向对比
- 不编造数据；数据缺失时明确说明

【回复格式】Markdown，关键指标用表格，状态用 🟢🟡🔴 标识。"""

OFFLINE_NOTICE = ("⚠️ 后端服务暂时不可用，当前仅提供知识库问答，"
                  "实时数据暂不可获取。")


@tool(name="task", tags=["orchestration"])
async def task(agent: str, instruction: str, context: str = "") -> str:
    """派遣子智能体执行任务（FIFO 排队，最大 5 并发）。

    Args:
        agent: 子智能体名称（topology-analyst/data-collector/analysis-expert/report-generator/rag-retriever）
        instruction: 任务指令
        context: 附加上下文（可选）
    """
    return await dispatch_subagent(agent, instruction, context)


def _lead_tools() -> list[dict]:
    # Lead 仅持有 task 工具 + 直接查询快捷工具
    return tool_schemas(["task", "fiber_stats_query", "rag_query"])


class Orchestrator:
    def __init__(self) -> None:
        self.chain = build_chain()
        # 将降级中间件注入 LLM 客户端
        from src.agents.llm import init_llm
        deg_mw = next(mw for mw in self.chain.mws
                      if mw.__class__.__name__ == "ModelDegradationMiddleware")
        init_llm(deg_mw)

    async def run(self, session_id: str,
                  user_message: str) -> AsyncIterator[dict]:
        """执行一轮对话，流式产出事件：
        {type: thought|tool_call|tool_result|subagent|token|warning|done|error}
        """
        started = time.perf_counter()
        ctx = RunContext(session_id=session_id, offline=backend.offline)
        OFFLINE_MODE.set(1 if backend.offline else 0)

        # 短期记忆
        history = await memory.get_recent(session_id)
        await memory.append_message(session_id, "user", user_message)
        ctx.messages = history + [{"role": "user", "content": user_message}]

        system = LEAD_SYSTEM_PROMPT
        if ctx.offline:
            system += f"\n\n【离线模式】{OFFLINE_NOTICE} 仅使用 rag_query 回答知识类问题。"
            yield {"type": "warning", "content": OFFLINE_NOTICE}

        # before_model（含 RAG 注入）
        await self.chain.before_model(ctx)
        if ctx.knowledge_snippets:
            refs = "\n".join(
                f"- [{s['source']}] {s['text'][:200]}"
                for s in ctx.knowledge_snippets)
            system += f"\n\n【相关知识（检索注入）】\n{refs}"
            yield {"type": "thought",
                   "content": f"已注入 {len(ctx.knowledge_snippets)} 条知识库片段"}

        messages = [{"role": "system", "content": system}] + ctx.messages
        lead_max_iter = settings.agents["lead"]["max_iterations"]
        final_text = ""

        try:
            for iteration in range(lead_max_iter):
                # 流式调用
                stream = await llm.chat(messages, tools=_lead_tools(),
                                        stream=True)
                content_buf, tool_calls_buf = [], {}
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        content_buf.append(delta.content)
                        yield {"type": "token", "content": delta.content}
                    if delta and delta.tool_calls:
                        for tc in delta.tool_calls:
                            slot = tool_calls_buf.setdefault(
                                tc.index, {"id": "", "name": "", "args": ""})
                            if tc.id: slot["id"] = tc.id
                            if tc.function and tc.function.name:
                                slot["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                slot["args"] += tc.function.arguments

                final_text = "".join(content_buf)

                if not tool_calls_buf:
                    break   # 无工具调用 → 结束

                # 组装 assistant 消息
                messages.append({
                    "role": "assistant", "content": final_text or None,
                    "tool_calls": [{
                        "id": tc["id"], "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    } for tc in tool_calls_buf.values()],
                })

                # 执行工具（并行）
                async def _exec(tc):
                    name, args_raw = tc["name"], tc["args"]
                    try:
                        args = json.loads(args_raw or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield_ev = {"type": "tool_call", "tool": name, "args": args}
                    await self.chain.before_tool(ctx, name, args)
                    try:
                        if name == "task":
                            result = await dispatch_subagent(
                                args.get("agent", ""),
                                args.get("instruction", ""),
                                args.get("context", ""))
                            result_str = result
                            ev = {"type": "subagent",
                                  "agent": args.get("agent"),
                                  "content": result[:500]}
                        else:
                            result = await execute_tool(name, args)
                            result_str = json.dumps(result, ensure_ascii=False,
                                                    default=str)
                            ev = {"type": "tool_result", "tool": name,
                                  "content": result_str[:500]}
                        await self.chain.after_tool(ctx, name, args, result)
                        return (yield_ev, ev,
                                {"role": "tool", "tool_call_id": tc["id"],
                                 "content": result_str})
                    except Exception as e:
                        err = json.dumps({"error": str(e)}, ensure_ascii=False)
                        await self.chain.after_tool(ctx, name, args,
                                                    {"error": str(e)})
                        return (yield_ev,
                                {"type": "tool_result", "tool": name,
                                 "content": err},
                                {"role": "tool", "tool_call_id": tc["id"],
                                 "content": err})

                results = await asyncio.gather(
                    *[_exec(tc) for tc in tool_calls_buf.values()])
                for ev0, ev1, tool_msg in results:
                    yield ev0
                    yield ev1
                    messages.append(tool_msg)

            # 领域校验告警随最终回复输出
            if ctx.warnings:
                for w in ctx.warnings:
                    yield {"type": "warning", "content": w}

            await memory.append_message(session_id, "assistant", final_text)
            await self.chain.after_model(ctx, final_text)
            yield {"type": "done", "trace_id": ctx.trace_id,
                   "elapsed_ms": round((time.perf_counter() - started) * 1000)}
            AGENT_REQUESTS.labels(status="ok").inc()

        except ModelCircuitOpen:
            AGENT_REQUESTS.labels(status="degraded").inc()
            await notifier.send_critical("Agent 模型熔断",
                                         "LLM 连续失败已熔断，60s 后自动恢复试探")
            yield {"type": "error",
                   "content": "⚠️ AI 推理服务暂时不可用（已熔断），请稍后重试。"
                              "知识库问答仍可通过前端检索测试使用。"}
        except Exception as e:
            logger.exception("编排异常")
            AGENT_REQUESTS.labels(status="error").inc()
            yield {"type": "error", "content": f"处理失败: {e}"}
        finally:
            AGENT_REQUEST_DURATION.observe(time.perf_counter() - started)


orchestrator = Orchestrator()