"""Lead Agent 编排器：意图识别 → task 派遣 → 结果汇总（SSE 流式输出）。"""
from __future__ import annotations
import asyncio, json, logging, time
from typing import AsyncIterator

from src.settings import settings
from src.tools.registry import tool_schemas, execute_tool, tool
from src.agents.llm import ModelCircuitOpen, get_llm
from src.agents.scheduler import dispatch_subagent
from src.agents.sub_agents import SUBAGENTS
from src.middlewares import RunContext, build_chain
from src.memory.store import memory
from src.mcp import backend
from src.notify.notifier import notifier
from src.monitoring.metrics import (AGENT_REQUESTS, AGENT_REQUEST_DURATION,
                                    OFFLINE_MODE)

logger = logging.getLogger("fiber.lead")

LEAD_SYSTEM_PROMPT = """你是光纤维护服务系统的智能分析助手（Lead Agent v3.2.1）。

【核心职责】
1. 理解用户的光纤分析需求（单条分析/批量分析/趋势查询/巡检/知识问答/报告导出）
2. 通过 task 工具派遣合适的子智能体执行，再汇总结果
3. 生成结构化最终回复

【可用子智能体】（通过 task 工具派遣，agent 参数取以下名称）
- topology-analyst: 查询光纤连接、单盘、网元信息
- data-collector: 获取性能、衰耗、告警、颜色、统计、趋势数据（支持批量）
- analysis-expert: 解读衰耗/颜色结果、异常检测、趋势与对比分析
- report-generator: 生成结构化报告、维护建议、文件导出（PDF/Excel/CSV）
- knowledge-assistant: 检索知识库 + 记忆查询，回答光纤领域知识问题

【fiber_id 格式规则（极重要）】
- 后端 API 的 fiber_id 必须是纯数字（如 65），不是 "F65" 或 "F065"
- 用户输入 "F65"/"F065"/"光纤65" 时，必须提取数字部分 65 作为 fiber_id
- 在指令中明确告知子智能体使用数字 fiber_id

【执行顺序约束】
- 单纤分析流程：topology-analyst（解析拓扑）→ data-collector（采集数据）→ analysis-expert（解读分析）→ report-generator（生成报告）→ 你汇总最终回复
- 每个子智能体的 instruction 中必须包含数字 fiber_id
- data-collector 的指令应包含 topology-analyst 返回的拓扑信息
- analysis-expert 的指令应包含前两步的结果摘要
- report-generator 的指令应包含 analysis-expert 的分析结论，由其检索知识库并生成维护建议

【report-generator 触发规则（极重要）】
- 当用户要求“分析报告”“质量报告”“导出报告”时，必须在 analysis-expert 完成后派遣 report-generator
- report-generator 负责：检索知识库（rag_query）、生成维护建议、导出文件（PDF/Excel/CSV）
- 单纤分析流程的最后一步必须是 report-generator，而不是你直接汇总

【rag_query 与 knowledge-assistant 触发规则】
- 用户问知识类问题（如“什么是OTDR”“衰耗标准是什么”）：你直接调用 rag_query 回答，无需派遣子智能体
- 用户问历史分析结果：你直接调用 memory_query 回答
- 当分析流程中需要引用知识库条款时，派遣 report-generator 或 knowledge-assistant 处理

【批量分析规则（极重要）】
- 当用户要求分析多条光纤（如“分析 F65~F75”）时，禁止循环派遣 Sub-Agent
- 正确做法：派遣 data-collector 一次，指令中列出所有 fiber_id，让其使用 batch 工具一次性采集
- 然后派遣 analysis-expert 一次，传入批量采集结果进行汇总分析
- 最后派遣 report-generator 一次，生成批量分析报告
- 单次批量查询最大 200 条

【重要约束】
- 衰耗计算和颜色判定由后端 C++ 服务完成，你只调用 API 获取结果并解读
- 操作对象仅限网元间连纤（src_ne_id ≠ dst_ne_id）
- 支持对比分析：同一光纤不同时间点 / 同网元对横向对比
- 不编造数据；数据缺失时明确说明

【回复格式（极重要）】
你的最终回复必须严格遵循以下格式规则，前端会按标记渲染：
- 一级标题：用 ## 开头（独占一行），如 `## 光纤 F65 质量分析报告`
- 二级标题：用 ### 开头（独占一行），如 `### 1. 基础拓扑信息`
- 列表项：用 - 开头（独占一行），如 `- 源端网元：NE 106`
- 分隔线：用 --- 独占一行
- 关键指标：用 **加粗** 标注指标名，如 **衰耗值**：0.0 dBm
- 状态标识：用 🟢🔴 标识状态
- 禁止使用 markdown 表格（| 列 | 列 |），改用逐行列出
- 禁止使用 # 单井号标题
- 每段内容结束后空一行

示例格式：
## 光纤 F65 质量分析报告

### 1. 基础拓扑信息
- **光纤 ID**：65
- **连接类型**：网元间连纤
- **源端**：NE 106 (单盘: 10065, 端口: 1)
- **宿端**：NE 107 (单盘: 20065, 端口: 1)

### 2. 质量评估
- **当前状态**：🔴 红色连纤（严重）
- **衰耗值**：0.0 dBm

---

### 3. 维护建议
- 检查源端 NE 106 单盘 10065 端口 1 的光模块状态
- 若为长距离传输，建议进行 OTDR 测试
"""

OFFLINE_NOTICE = ("⚠️ 后端服务暂时不可用，当前仅提供知识库问答，"
                  "实时数据暂不可获取。")


@tool(name="task", tags=["orchestration"])
async def task(agent: str, instruction: str, context: str = "") -> str:
    """派遣子智能体执行任务（FIFO 排队，最大 5 并发）。

    Args:
        agent: 子智能体名称（topology-analyst/data-collector/analysis-expert/report-generator/knowledge-assistant）
        instruction: 任务指令
        context: 附加上下文（可选）
    """
    return await dispatch_subagent(agent, instruction, context)


def _smart_truncate(text: str, max_len: int = 2000) -> str:
    """智能截断：保留数值数据完整性，优先截断描述性文本。

    策略：
    1. 若 text 在 max_len 以内，原样返回
    2. 尝试解析 JSON：保留所有数值字段，截断字符串字段
    3. 纯文本：保留包含数字的行，截断其余
    """
    if len(text) <= max_len:
        return text

    # 尝试 JSON 解析（Sub-Agent 返回结构化数据）
    try:
        import re as _re
        data = json.loads(text)
        if isinstance(data, dict):
            # 保留数值字段，截断字符串字段
            preserved = {}
            for k, v in data.items():
                if isinstance(v, (int, float, bool)):
                    preserved[k] = v  # 数值完整保留
                elif isinstance(v, str) and len(v) > 200:
                    preserved[k] = v[:200] + "...[截断]"
                elif isinstance(v, list) and len(str(v)) > 500:
                    preserved[k] = v[:5]  # 只保留前 5 项
                    if len(v) > 5:
                        preserved[f"{k}_note"] = f"...共 {len(v)} 项，已截断"
                else:
                    preserved[k] = v
            result = json.dumps(preserved, ensure_ascii=False)
            return result[:max_len] if len(result) > max_len else result
    except (json.JSONDecodeError, TypeError):
        pass

    # 纯文本策略：保留包含数字的行
    lines = text.split("\n")
    import re as _re
    numeric_lines = []
    text_lines = []
    for line in lines:
        if _re.search(r'\d+\.?\d*\s*(?:dB|dBm|ms|条|个|%)', line):
            numeric_lines.append(line)  # 含数值单位的行优先保留
        else:
            text_lines.append(line)

    # 先填数值行，剩余空间填文本行
    result_lines = numeric_lines[:]
    remaining = max_len - sum(len(l) + 1 for l in result_lines)
    for line in text_lines:
        if remaining <= 0:
            break
        result_lines.append(line)
        remaining -= len(line) + 1

    result = "\n".join(result_lines)
    if len(result) > max_len:
        result = result[:max_len]
    return result + "\n...[截断]"


def _lead_tools() -> list[dict]:
    # Lead 仅持有 task 工具 + 直接查询快捷工具
    return tool_schemas(["task", "fiber_stats_query", "rag_query", "memory_query"])


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
        logger.info("[Orchestrator] 开始 session=%s msg_len=%d offline=%s",
                    session_id, len(user_message), backend.offline)
        ctx = RunContext(session_id=session_id, offline=backend.offline)
        OFFLINE_MODE.set(1 if backend.offline else 0)

        # 短期记忆
        history = await memory.get_recent(session_id)
        await memory.append_message(session_id, "user", user_message)
        ctx.messages = history + [{"role": "user", "content": user_message}]
        logger.info("[Orchestrator] session=%s history_count=%d", session_id, len(history))

        system = LEAD_SYSTEM_PROMPT
        if ctx.offline:
            system += f"\n\n【离线模式】{OFFLINE_NOTICE} 仅使用 rag_query 回答知识类问题。"
            logger.warning("[Orchestrator] session=%s 离线模式", session_id)
            yield {"type": "warning", "content": OFFLINE_NOTICE}

        # before_model（含 RAG 注入）
        t_mw = time.perf_counter()
        await self.chain.before_model(ctx)
        logger.info("[Orchestrator] before_model 耗时=%.0fms", (time.perf_counter() - t_mw) * 1000)
        if ctx.knowledge_snippets:
            refs = "\n".join(
                f"- [{s['source']}] {s['text'][:200]}"
                for s in ctx.knowledge_snippets)
            system += f"\n\n【相关知识（检索注入）】\n{refs}"
            logger.info("[Orchestrator] RAG 注入 %d 条片段", len(ctx.knowledge_snippets))
            yield {"type": "thought",
                   "content": f"已注入 {len(ctx.knowledge_snippets)} 条知识库片段"}

        messages = [{"role": "system", "content": system}] + ctx.messages
        lead_max_iter = settings.agents["lead"]["max_iterations"]
        final_text = ""
        _nudge_count = 0   # 空工具调用提醒计数（最多提醒 1 次）

        try:
            for iteration in range(lead_max_iter):
                logger.info("[Orchestrator] session=%s iteration=%d/%d",
                            session_id, iteration + 1, lead_max_iter)
                # 流式调用
                t_llm = time.perf_counter()
                stream = await get_llm().chat(messages, tools=_lead_tools(),
                                        stream=True)
                content_buf, tool_calls_buf = [], {}
                token_count = 0
                async for chunk in stream:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        content_buf.append(delta.content)
                        token_count += 1
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

                llm_ms = (time.perf_counter() - t_llm) * 1000
                final_text = "".join(content_buf)
                logger.info("[Orchestrator] LLM 返回 tokens=%d tool_calls=%d 耗时=%.0fms",
                            token_count, len(tool_calls_buf), llm_ms)

                if not tool_calls_buf:
                    # ── 空工具调用保护：首轮无 tool_call 时提醒 LLM 必须使用工具 ──
                    if _nudge_count == 0 and token_count > 0:
                        _nudge_count += 1
                        logger.warning(
                            "[Orchestrator] 首轮无工具调用，注入 task 工具提醒 "
                            "session=%s content_preview=%.120s",
                            session_id, final_text[:120])
                        # 将 LLM 的回复作为 assistant 消息保留，追加提醒
                        messages.append({"role": "assistant", "content": final_text})
                        messages.append({
                            "role": "user",
                            "content": (
                                "【系统提醒】你刚才只是描述了计划但未执行。"
                                "你必须立即使用 task 工具派遣子智能体来完成任务，"
                                "不要只输出文字说明。例如：调用 task(agent='topology-analyst', "
                                "instruction='...') 来开始执行。"
                            ),
                        })
                        continue  # 重新迭代
                    logger.info("[Orchestrator] 无工具调用，结束迭代")
                    break   # 无工具调用 → 结束

                # 组装 assistant 消息
                messages.append({
                    "role": "assistant", "content": final_text or None,
                    "tool_calls": [{
                        "id": tc["id"], "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["args"]},
                    } for tc in tool_calls_buf.values()],
                })

                # ── 分类工具调用：task（顺序）vs 其他（并行） ──
                task_calls = []   # Sub-Agent 派遣（有数据依赖，须顺序执行）
                other_calls = []  # 普通工具（可并行）
                for tc in tool_calls_buf.values():
                    if tc["name"] == "task":
                        task_calls.append(tc)
                    else:
                        other_calls.append(tc)
                # Sub-Agent 执行顺序：拓扑→采集→分析→报告→知识
                _AGENT_ORDER = {"topology-analyst": 0, "data-collector": 1,
                                "analysis-expert": 2, "report-generator": 3,
                                "knowledge-assistant": 4}
                task_calls.sort(key=lambda tc: _AGENT_ORDER.get(
                    json.loads(tc["args"] or "{}").get("agent", ""), 99))

                logger.info("[Orchestrator] 工具分类: task=%d(顺序) other=%d(并行)",
                            len(task_calls), len(other_calls))

                async def _exec(tc, extra_context=""):
                    name, args_raw = tc["name"], tc["args"]
                    try:
                        args = json.loads(args_raw or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    # 注入上游上下文（仅 task 工具）
                    if name == "task" and extra_context:
                        existing = args.get("context", "")
                        args["context"] = (existing + "\n" + extra_context).strip()
                    logger.info("[Orchestrator] 执行工具 tool=%s args=%.200s",
                                name, json.dumps(args, ensure_ascii=False)[:200])
                    yield_ev = {"type": "tool_call", "tool": name, "args": args}
                    await self.chain.before_tool(ctx, name, args)
                    try:
                        t_tool = time.perf_counter()
                        if name == "task":
                            agent_name = args.get("agent", "")
                            instruction = args.get("instruction", "")
                            context_str = args.get("context", "")
                            logger.info("[Orchestrator] 派遣 sub-agent=%s instruction=%.120s context_len=%d",
                                        agent_name, instruction[:120], len(context_str))
                            result = await dispatch_subagent(
                                agent_name, instruction, context_str)
                            result_str = result
                            # 空结果检测与告警
                            if not result or not result.strip():
                                logger.warning("[Orchestrator] sub-agent=%s 返回空结果，注入错误提示",
                                               agent_name)
                                result_str = (f"[{agent_name}] 未获取到有效数据，"
                                              f"可能是 fiber_id 格式不匹配或后端无数据。")
                            ev = {"type": "subagent",
                                  "agent": agent_name,
                                  "content": result_str[:500]}
                            logger.info("[Orchestrator] sub-agent=%s 完成 result_len=%d 耗时=%.0fms",
                                        agent_name, len(result_str),
                                        (time.perf_counter() - t_tool) * 1000)
                        else:
                            result = await execute_tool(name, args)
                            result_str = json.dumps(result, ensure_ascii=False,
                                                    default=str)
                            ev = {"type": "tool_result", "tool": name,
                                  "content": result_str[:500]}
                            logger.info("[Orchestrator] 工具 %s 完成 result_len=%d 耗时=%.0fms",
                                        name, len(result_str),
                                        (time.perf_counter() - t_tool) * 1000)
                        await self.chain.after_tool(ctx, name, args, result)
                        return (yield_ev, ev,
                                {"role": "tool", "tool_call_id": tc["id"],
                                 "content": result_str})
                    except Exception as e:
                        tool_ms = (time.perf_counter() - t_tool) * 1000
                        logger.error("[Orchestrator] 工具 %s 异常 耗时=%.0fms error=%s",
                                     name, tool_ms, e, exc_info=True)
                        err = json.dumps({"error": str(e)}, ensure_ascii=False)
                        await self.chain.after_tool(ctx, name, args,
                                                    {"error": str(e)})
                        return (yield_ev,
                                {"type": "tool_result", "tool": name,
                                 "content": err},
                                {"role": "tool", "tool_call_id": tc["id"],
                                 "content": err})

                # ── 1) 顺序执行 task 工具，累积上下文 ──
                accumulated_context = ""
                for tc in task_calls:
                    ev0, ev1, tool_msg = await _exec(tc, accumulated_context)
                    yield ev0
                    yield ev1
                    messages.append(tool_msg)
                    # 将本 step 结果注入后续 task 上下文（智能截断）
                    content = tool_msg.get("content", "")
                    if content and not content.startswith('{"error"'):
                        agent_name = json.loads(tc["args"] or "{}").get("agent", "unknown")
                        truncated = _smart_truncate(content, max_len=2000)
                        accumulated_context += f"\n【{agent_name} 结果】\n{truncated}"

                # ── 2) 并行执行其他工具 ──
                if other_calls:
                    results = await asyncio.gather(
                        *[_exec(tc) for tc in other_calls])
                    for ev0, ev1, tool_msg in results:
                        yield ev0
                        yield ev1
                        messages.append(tool_msg)

            # 领域校验告警随最终回复输出
            if ctx.warnings:
                for w in ctx.warnings:
                    logger.warning("[Orchestrator] 领域告警: %.100s", w[:100])
                    yield {"type": "warning", "content": w}

            await memory.append_message(session_id, "assistant", final_text)
            await self.chain.after_model(ctx, final_text)
            total_ms = (time.perf_counter() - started) * 1000
            logger.info("[Orchestrator] 完成 session=%s final_text_len=%d total=%.0fms",
                        session_id, len(final_text), total_ms)
            yield {"type": "done", "trace_id": ctx.trace_id,
                   "elapsed_ms": round(total_ms)}
            AGENT_REQUESTS.labels(status="ok").inc()

        except ModelCircuitOpen:
            AGENT_REQUESTS.labels(status="degraded").inc()
            logger.error("[Orchestrator] 模型熔断 session=%s", session_id)
            await notifier.send_critical("Agent 模型熔断",
                                         "LLM 连续失败已熔断，60s 后自动恢复试探")
            yield {"type": "error",
                   "content": "⚠️ AI 推理服务暂时不可用（已熔断），请稍后重试。"
                              "知识库问答仍可通过前端检索测试使用。"}
        except Exception as e:
            logger.exception("[Orchestrator] 编排异常 session=%s", session_id)
            AGENT_REQUESTS.labels(status="error").inc()
            yield {"type": "error", "content": f"处理失败: {e}"}
        finally:
            AGENT_REQUEST_DURATION.observe(time.perf_counter() - started)


orchestrator = Orchestrator()