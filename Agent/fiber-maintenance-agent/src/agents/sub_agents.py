"""5 个 Sub-Agent 定义 + 运行器（v3.2.1）。

model_profile 与 temperature/top_p 的优先级：
  config.yaml agents.subagents.<name> > SubAgentSpec 硬编码默认值
model_profile 通过 LLMClient.chat(model_profile=...) 生效，
运行时按 config.yaml llm.models 切换实际模型。
"""
from __future__ import annotations
import json, logging
from dataclasses import dataclass, field

from src.settings import settings
from src.tools.registry import tool_schemas, execute_tool
from src.agents.llm import get_llm

logger = logging.getLogger("fiber.subagent")

# config.yaml 中子 agent 配置键名（下划线）→ Sub-Agent 名（连字符）的映射
_CONFIG_KEY_MAP = {
    "data_collector": "data-collector",
    "analysis_expert": "analysis-expert",
    "knowledge_assistant": "knowledge-assistant",
    "report_generator": "report-generator",
    "topology_analyst": "topology-analyst",
}

@dataclass
class SubAgentSpec:
    name: str
    description: str
    model_profile: str            # fast / primary
    tools: list[str]
    system_prompt: str
    temperature: float = 0.3
    top_p: float = 0.9
    max_iterations: int = field(
        default_factory=lambda: settings.agents["subagents"]["max_iterations"])


SUBAGENTS: dict[str, SubAgentSpec] = {
    "topology-analyst": SubAgentSpec(
        name="topology-analyst",
        description="查询光纤连接、单盘、网元信息",
        model_profile="fast",
        tools=["fiber_connection_query", "batch_fiber_connection_query",
               "board_query", "ne_query"],
        temperature=0.0,
        system_prompt="""你是拓扑分析专家。职责：查询连纤连接信息、单盘信息、网元信息。
约束：
- 不做场景判定、不做颜色计算（由后端完成）
- 仅关注网元间连纤（src_ne_id ≠ dst_ne_id），发现网元内连纤需注明
- 输出结构化 JSON 摘要 + 简要说明"""),

    "data-collector": SubAgentSpec(
        name="data-collector",
        description="采集性能、衰耗、告警、颜色、统计、趋势数据",
        model_profile="fast",          # §3.2.2: fast 模式，纯工具调用
        tools=["fiber_performance_query", "fiber_spanloss_query",
               "alarm_query", "colored_fibers_query",
               "all_colored_fibers_query", "fiber_stats_query",
               "fiber_trend_query",
               "batch_fiber_performance_query", "batch_fiber_spanloss_query"],
        temperature=0.0,
        system_prompt="""你是数据采集专家。职责：按指令采集光纤性能、衰耗、告警、颜色、统计、趋势数据。
约束：
- 仅采集，不做分析判断
- 数据原样返回（含单位 dBm/dB），缺失数据明确标注
- 批量采集时使用 batch 工具提高效率
- 输出结构化 JSON 摘要
- 严格按照各工具的参数定义调用（见工具描述），不要凭猜测传参"""),

    "analysis-expert": SubAgentSpec(
        name="analysis-expert",
        description="解读衰耗/颜色结果、异常检测、趋势与对比分析",
        model_profile="primary",       # §3.2.3: primary 模式，需要推理能力
        tools=["memory_query", "memory_save"],
        temperature=0.1,
        top_p=0.3,
        system_prompt="""你是光纤分析专家。职责：解读已有计算结果（衰耗/颜色/场景）、异常检测、趋势分析、对比分析。
约束：
- 不做沙箱计算，仅解读 API 返回值（由 data-collector 采集后传入上下文）
- 颜色语义：🟢正常 / 🟡关注（次要告警/劣化）/ 🔴紧急（中断/严重故障）
- 对比分析：纵向（同一光纤不同时间，用 memory_query）/ 横向（同网元对多连纤）
- 分析完成后用 memory_save 持久化结果
- 结论需给出判定依据（阈值/规范引用）"""),

    "report-generator": SubAgentSpec(
        name="report-generator",
        description="生成结构化报告、维护建议、文件导出",
        model_profile="primary",       # §3.2.4: primary 模式，需要生成能力
        tools=["rag_query", "memory_query", "export_pdf", "export_excel", "export_csv"],
        temperature=0.3,
        system_prompt="""你是报告生成专家。职责：生成结构化分析报告、维护建议，支持导出 PDF/Excel/CSV。
约束：
- 报告结构：概览 → 详细分析 → 处理建议（按 P0~P3 排序）→ 参考知识
- 维护建议必须引用知识库条款（rag_query 检索）
- 可使用 memory_query 获取历史分析结果
- 导出时返回下载链接与有效期（24h）"""),

    "knowledge-assistant": SubAgentSpec(
        name="knowledge-assistant",
        description="检索知识库 + 记忆查询，回答光纤领域知识问题",
        model_profile="fast",
        tools=["rag_query", "memory_query", "vector_search", "bm25_search"],
        temperature=0.5,
        system_prompt="""你是知识检索与问答专家。职责：混合检索光纤领域知识库，回答领域知识问题。
约束：
- 优先 rag_query（混合检索+重排）
- 返回片段需标注来源文档与相关度
- 无命中时明确说明，不编造
- 可结合 memory_query 获取历史上下文"""),
}


def _resolve_subagent_params(spec: SubAgentSpec) -> dict:
    """从 config.yaml 读取子 agent 的 temperature/top_p，缺省回退到 spec 硬编码值。

    优先级: config.yaml agents.subagents.<config_key> > SubAgentSpec 默认值
    """
    sub_cfg = settings.agents.get("subagents", {})
    # 将 spec.name（连字符）反查为 config_key（下划线）
    config_key = None
    for ck, sn in _CONFIG_KEY_MAP.items():
        if sn == spec.name:
            config_key = ck
            break
    agent_cfg = sub_cfg.get(config_key, {}) if config_key else {}
    return {
        "temperature": agent_cfg.get("temperature", spec.temperature),
        "top_p": agent_cfg.get("top_p", spec.top_p),
    }


async def run_subagent(name: str, instruction: str, context: str = "") -> str:
    """运行指定 Sub-Agent 的独立推理循环。"""
    import time
    spec = SUBAGENTS.get(name)
    if spec is None:
        logger.warning("[SubAgent] 未知子智能体: %s", name)
        return f"未知的子智能体: {name}"

    # 从配置读取 temperature/top_p（覆盖 spec 硬编码默认值）
    params = _resolve_subagent_params(spec)

    t0 = time.perf_counter()
    logger.info("[SubAgent] 启动 name=%s model_profile=%s temperature=%.2f top_p=%.2f tools=%s instruction=%.120s",
                name, spec.model_profile, params["temperature"], params["top_p"],
                spec.tools, instruction[:120])

    messages = [
        {"role": "system", "content": spec.system_prompt},
        {"role": "user", "content":
         f"{instruction}" + (f"\n\n【上下文】\n{context}" if context else "")},
    ]
    schemas = tool_schemas(spec.tools)

    for iteration in range(spec.max_iterations):
        logger.info("[SubAgent] name=%s iteration=%d/%d", name, iteration + 1, spec.max_iterations)
        t_llm = time.perf_counter()
        resp = await get_llm().chat(
            messages, tools=schemas or None,
            temperature=params["temperature"],
            top_p=params["top_p"],
            model_profile=spec.model_profile)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            content = msg.content or ""
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info("[SubAgent] name=%s 完成 content_len=%d iterations=%d elapsed=%.0fms",
                        name, len(content), iteration + 1, elapsed)
            # 空结果保护：LLM 未产生内容也未调用工具，返回明确提示
            if not content.strip():
                logger.warning("[SubAgent] name=%s LLM 返回空内容，无工具调用",
                               name)
                return (f"[{name}] 未生成分析结果。"
                        f"请检查指令是否包含有效的 fiber_id（数字）以及必要参数。")
            return content

        logger.info("[SubAgent] name=%s LLM 返回 %d 个工具调用 耗时=%.0fms",
                    name, len(msg.tool_calls), (time.perf_counter() - t_llm) * 1000)

        # 并行执行该 sub-agent 本轮的全部工具调用
        import asyncio
        async def _exec(tc):
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
                logger.info("[SubAgent] name=%s 调用工具 %s args=%.200s",
                            name, tool_name, tc.function.arguments[:200])
                t_tool = time.perf_counter()
                result = await execute_tool(tool_name, args)
                logger.info("[SubAgent] name=%s 工具 %s 完成 耗时=%.0fms",
                            name, tool_name, (time.perf_counter() - t_tool) * 1000)
                return {"role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps(result, ensure_ascii=False,
                                              default=str)}
            except Exception as e:
                logger.error("[SubAgent] name=%s 工具 %s 异常 error=%s",
                             name, tool_name, e, exc_info=True)
                return {"role": "tool", "tool_call_id": tc.id,
                        "content": json.dumps({"error": str(e)},
                                              ensure_ascii=False)}
        tool_msgs = await asyncio.gather(*[_exec(tc) for tc in msg.tool_calls])
        messages.extend(tool_msgs)

    elapsed = (time.perf_counter() - t0) * 1000
    result = messages[-1].get("content", "") if isinstance(messages[-1], dict) \
        else (messages[-1].content or "")
    logger.info("[SubAgent] name=%s 达到最大迭代 content_len=%d elapsed=%.0fms",
                name, len(result), elapsed)
    return result