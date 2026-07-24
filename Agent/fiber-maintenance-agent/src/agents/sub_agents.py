"""5 个 Sub-Agent 定义 + 运行器。"""
from __future__ import annotations
import json, logging
from dataclasses import dataclass, field

from src.settings import settings
from src.tools.registry import tool_schemas, execute_tool
from src.agents.llm import llm

logger = logging.getLogger("fiber.subagent")

@dataclass
class SubAgentSpec:
    name: str
    description: str
    model_profile: str            # fast / primary
    tools: list[str]
    system_prompt: str
    max_iterations: int = field(
        default_factory=lambda: settings.agents["subagents"]["max_iterations"])


SUBAGENTS: dict[str, SubAgentSpec] = {
    "topology-analyst": SubAgentSpec(
        name="topology-analyst",
        description="查询光纤连接、单盘、网元信息",
        model_profile="fast",
        tools=["fiber_connection_query", "batch_fiber_connection_query",
               "board_query", "ne_query"],
        system_prompt="""你是拓扑分析专家。职责：查询连纤连接信息、单盘信息、网元信息。
约束：
- 不做场景判定、不做颜色计算（由后端完成）
- 仅关注网元间连纤（src_ne_id ≠ dst_ne_id），发现网元内连纤需注明
- 输出结构化 JSON 摘要 + 简要说明"""),

    "data-collector": SubAgentSpec(
        name="data-collector",
        description="采集性能、告警、颜色、统计、趋势数据",
        model_profile="fast",
        tools=["fiber_performance_query", "fiber_spanloss_query",
               "alarm_query", "colored_fibers_query",
               "all_colored_fibers_query", "fiber_stats_query",
               "fiber_trend_query"],
        system_prompt="""你是数据采集专家。职责：按指令采集光纤性能、衰耗、告警、颜色、统计、趋势数据。
约束：
- 仅采集，不做分析判断
- 数据原样返回（含单位 dBm/dB），缺失数据明确标注
- 输出结构化 JSON 摘要"""),

    "analysis-expert": SubAgentSpec(
        name="analysis-expert",
        description="解读衰耗/颜色结果、异常检测、趋势与对比分析",
        model_profile="primary",
        tools=["fiber_spanloss_query", "fiber_performance_query",
               "colored_fibers_query", "fiber_trend_query",
               "memory_query", "memory_save"],
        system_prompt="""你是光纤分析专家。职责：解读后端计算结果（衰耗/颜色/场景）、异常检测、趋势分析、对比分析。
约束：
- 不做沙箱计算，仅解读 API 返回值
- 颜色语义：🟢正常 / 🟡关注（次要告警/劣化）/ 🔴紧急（中断/严重故障）
- 对比分析：纵向（同一光纤不同时间，用 memory_query）/ 横向（同网元对多连纤）
- 分析完成后用 memory_save 持久化结果
- 结论需给出判定依据（阈值/规范引用）"""),

    "report-generator": SubAgentSpec(
        name="report-generator",
        description="生成结构化报告、维护建议、文件导出",
        model_profile="primary",
        tools=["rag_query", "read_file", "export_pdf", "export_excel", "export_csv"],
        system_prompt="""你是报告生成专家。职责：生成结构化分析报告、维护建议，支持导出 PDF/Excel/CSV。
约束：
- 报告结构：概览 → 详细分析 → 处理建议（按 P0~P3 排序）→ 参考知识
- 维护建议必须引用知识库条款（rag_query 检索）
- 可使用 read_file 读取本地文件作为报告素材
- 导出时返回下载链接与有效期（24h）"""),

    "rag-retriever": SubAgentSpec(
        name="rag-retriever",
        description="检索光纤领域知识库",
        model_profile="fast",
        tools=["rag_query", "vector_search", "bm25_search"],
        system_prompt="""你是知识检索专家。职责：混合检索光纤领域知识库，返回 Top-K 知识片段。
约束：
- 优先 rag_query（混合检索+重排）
- 返回片段需标注来源文档与相关度
- 无命中时明确说明，不编造"""),
}


async def run_subagent(name: str, instruction: str, context: str = "") -> str:
    """运行指定 Sub-Agent 的独立推理循环。"""
    spec = SUBAGENTS.get(name)
    if spec is None:
        return f"未知的子智能体: {name}"

    messages = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content":
         f"{instruction}" + (f"\n\n【上下文】\n{context}" if context else "")},
    ]
    schemas = tool_schemas(spec.tools)

    for _ in range(spec.max_iterations):
        resp = await llm.chat(messages, tools=schemas or None)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            return msg.content or ""

        # 并行执行该 sub-agent 本轮的全部工具调用
        import asyncio
        async def _exec(tc):
            try:
                args = json.loads(tc.function.arguments or "{}")
                result = await execute_tool(tc.function.name, args)
                return {"role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False,
                                              default=str)}
            except Exception as e:
                return {"role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps({"error": str(e)},
                                              ensure_ascii=False)}
        tool_msgs = await asyncio.gather(*[_exec(tc) for tc in msg.tool_calls])
        messages.extend(tool_msgs)

    return messages[-1].get("content", "") if isinstance(messages[-1], dict) \
        else (messages[-1].content or "")