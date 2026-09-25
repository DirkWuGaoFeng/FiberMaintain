"""
主编排图 —— v7.1-Final 版本。

【架构概述】
本模块是光纤维护 Agent 的核心编排层，采用 LangGraph StateGraph 实现。
架构设计包含三大核心机制：
  1. Harness 控制层：输入守卫 → 规则引擎 → 多路分发
  2. Controlled Loop 受控循环：数据收集 → 规则判断 → 分析专家 → 循环/输出
  3. Narrator 验证循环：叙述员 → 数字校验 → 模板兆底

【节点清单】（共 18 个节点）
  input_guard          - 输入守卫：拦截无效/危险输入
  rule_engine          - 规则引擎：正则匹配识别意图（零 LLM 调用）
  fast_path_executor   - 快速路径：规则命中时直接调用 API，跳过 LLM
  intent_classifier    - 意图分类器：LLM 识别规则未命中的意图
  param_gate           - 参数门禁：校验提取的参数是否完整合法
  clarification        - 澄清交互：向用户追问缺失参数
  intent_router        - 意图路由：根据意图分发到对应子图
  data_collector       - 数据收集子图：ReAct Agent 调用工具获取数据
  batch_dispatcher     - 批量派发器：拆分批量查询为并行任务
  knowledge_qa         - 知识问答子图：RAG 检索 + 生成回答
  rule_judgment        - 规则判断：程序化阈值判断（零 LLM 调用）
  analysis_expert      - 分析专家：LLM 推理是否需要补充数据
  narrator             - 叙述员：将结构化判断转为自然语言
  narrator_validator   - 叙述校验：检查数字是否被 LLM 幻觉篡改
  template_fallback    - 模板兆底：LLM 失败时用模板输出
  report_generator     - 报告生成：生成结构化维护报告
  report_evaluator     - 报告评估：评估报告质量，决定是否优化
  result_aggregator    - 结果聚合：整合各路径的输出为最终回复
  degradation_handler  - 降级处理：服务不可用时的降级策略

【四重终止保障】（防止无限循环）
  ① 轮次上限：loop_count ≤ max_loops（默认 3）
  ② LLM 预算：llm_call_count ≤ max_llm_calls（默认 10）
  ③ 无进展检测：连续相同动作签名 → no_progress_count 累加
  ④ 工具熔断：所有工具调用失败 → 触发降级

【面试常见问题】
  Q: 为什么用 LangGraph 而不是纯 LangChain？
  A: LangGraph 支持状态图、条件边、循环，适合复杂 Agent 编排；
     LangChain 的 Chain 是线性 DAG，无法表达循环和条件分支。

  Q: 为什么有 18 个节点这么多？
  A: 每个节点职责单一，便于独立测试、降级和监控。
     快速路径（fast_path）可以跳过大部分节点，延迟 <1s。
"""

from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from ..config import CHECKPOINT_DB
from .routing import (
    route_after_analysis,
    route_after_evaluation,
    route_after_narrator_validation,
    route_after_param_gate,
    route_after_rule_engine,
    route_by_intent,
)
from .state import MainGraphState

logger = logging.getLogger(__name__)


def build_main_graph():
    """构建主编排图（v7.1-Final）。

    【功能说明】
    创建并编译 LangGraph StateGraph，注册所有节点和边。
    支持 v8 模式切换（通过环境变量 AGENT_MODE=v8 启用三层架构）。

    【返回值】
        编译后的 StateGraph 实例，带有 SQLite 检查点器支持多轮对话

    【架构说明】
    - 使用 Lazy Import 避免循环依赖
    - 检查点器（Checkpointer）实现对话状态持久化，支持多轮追问
    - v8 模式是实验性的三层架构，默认使用 v7.1 模式
    """
    # v8 模式切换
    from ..v8.graph import build_v8_graph, is_v8_mode

    if is_v8_mode():
        logger.info("[MainGraph] AGENT_MODE=v8, using v8 three-layer architecture")
        return build_v8_graph()

    # 懒加载导入以避免循环依赖
    from ..graph.subgraphs.data_collector import data_collector_subgraph
    from ..graph.subgraphs.knowledge_assistant import knowledge_assistant_subgraph
    from ..nodes.analysis_expert import analysis_expert_node
    from ..nodes.batch_dispatcher import batch_dispatcher_node
    from ..nodes.clarification import clarification_node
    from ..nodes.degradation_handler import degradation_handler_node
    from ..nodes.fast_path_executor import fast_path_executor_node
    from ..nodes.input_guard import input_guard_node
    from ..nodes.intent_classifier import intent_classifier_node
    from ..nodes.intent_router import intent_router_node
    from ..nodes.narrator import narrator_node
    from ..nodes.narrator_validator import narrator_validator_node
    from ..nodes.param_gate import param_gate_node
    from ..nodes.report_evaluator import report_evaluator_node
    from ..nodes.report_generator import report_generator_node
    from ..nodes.result_aggregator import result_aggregator_node
    from ..nodes.rule_engine import rule_engine_node
    from ..nodes.rule_judgment import rule_judgment_node
    from ..nodes.template_fallback import template_fallback_node

    graph = StateGraph(MainGraphState)

    # ===== 节点注册（共 18 个节点）=====
    # 【面试知识点】LangGraph 的 add_node 接受函数或 Runnable，
    # 函数签名必须为 async def node(state: State) -> dict
    graph.add_node("input_guard", input_guard_node)
    graph.add_node("rule_engine", rule_engine_node)
    graph.add_node("fast_path_executor", fast_path_executor_node)
    graph.add_node("intent_classifier", intent_classifier_node)
    graph.add_node("param_gate", param_gate_node)
    graph.add_node("clarification", clarification_node)
    graph.add_node("intent_router", intent_router_node)
    graph.add_node("data_collector", data_collector_subgraph)
    graph.add_node("rule_judgment", rule_judgment_node)
    graph.add_node("analysis_expert", analysis_expert_node)
    graph.add_node("narrator", narrator_node)
    graph.add_node("narrator_validator", narrator_validator_node)
    graph.add_node("template_fallback", template_fallback_node)
    graph.add_node("report_generator", report_generator_node)
    graph.add_node("report_evaluator", report_evaluator_node)
    graph.add_node("batch_dispatcher", batch_dispatcher_node)
    graph.add_node("knowledge_qa", knowledge_assistant_subgraph)
    graph.add_node("result_aggregator", result_aggregator_node)
    graph.add_node("degradation_handler", degradation_handler_node)

    # ===== 边定义（节点间的连接关系）=====
    # 【面试知识点】LangGraph 支持两种边：
    # - add_edge: 固定边，A → B 无条件跳转
    # - add_conditional_edges: 条件边，根据路由函数返回值决定下一节点

    # 入口：input_guard → rule_engine
    # 【设计意图】所有输入先经过守卫过滤，再进入规则引擎
    graph.add_edge(START, "input_guard")
    graph.add_edge("input_guard", "rule_engine")

    # 规则引擎 → 三路分发
    # - fast_path: 规则完全命中，直接执行 API 调用（延迟 <1s）
    # - rule_hit_complex: 规则命中但需要复杂处理（如批量查询）
    # - rule_miss: 规则未命中，交给 LLM 意图分类器
    graph.add_conditional_edges(
        "rule_engine",
        route_after_rule_engine,
        {
            "fast_path": "fast_path_executor",
            "rule_hit_complex": "param_gate",
            "rule_miss": "intent_classifier",
        },
    )

    # 快速路径 → 直接输出结果（跳过所有 LLM 节点）
    graph.add_edge("fast_path_executor", "result_aggregator")

    # LLM 意图分类 → 参数门禁
    # 【设计意图】无论意图来自规则还是 LLM，都必须经过参数校验
    graph.add_edge("intent_classifier", "param_gate")

    # 参数门禁 → 澄清交互 或 意图路由
    # - need_clarification: 参数不完整，向用户追问
    # - params_ok: 参数完整，进入意图路由
    graph.add_conditional_edges(
        "param_gate",
        route_after_param_gate,
        {
            "need_clarification": "clarification",
            "params_ok": "intent_router",
        },
    )

    # 澄清交互 → 结果聚合（输出追问消息，终止当前轮）
    # 【设计说明】MVP 阶段不支持 interrupt，追问消息作为当前轮最终输出。
    # 用户补充信息后发起新一轮对话，重新走规则引擎。
    # 未来启用 interrupt 时可改回：clarification → rule_engine（带新 user_input）
    graph.add_edge("clarification", "result_aggregator")

    # 意图路由 → 各子图
    # 【设计意图】根据意图类型分发到专门的处理子图，实现关注点分离
    graph.add_conditional_edges(
        "intent_router",
        route_by_intent,
        {
            "data_query": "data_collector",
            "batch_query": "batch_dispatcher",
            "knowledge_qa": "knowledge_qa",
            "report": "data_collector",
            "chitchat": "result_aggregator",
        },
    )

    # ===== 核心：受控循环（Controlled Loop）=====
    # 【面试知识点】这是 ReAct 模式的核心实现：
    # Reasoning（分析专家）→ Acting（数据收集）→ 循环直到得出结论
    # 通过四重终止保障防止无限循环
    graph.add_edge("data_collector", "rule_judgment")
    graph.add_edge("rule_judgment", "analysis_expert")

    # 分析专家 → 四路分发（循环核心）
    # - need_more_data: 需要补充数据，回到数据收集（ReAct 循环）
    # - generate_report: 数据充足，生成报告
    # - direct_narrate: 简单查询，直接叙述输出
    # - degraded: 服务降级，进入降级处理
    graph.add_conditional_edges(
        "analysis_expert",
        route_after_analysis,
        {
            "need_more_data": "data_collector",  # ReAct 循环回边
            "generate_report": "report_generator",
            "direct_narrate": "narrator",
            "degraded": "degradation_handler",
        },
    )

    # ===== 叙述员 → 校验器 → 验证循环 [v7.1] =====
    # 【设计意图】LLM 容易在数字上产生幻觉，这里增加一层校验
    graph.add_edge("narrator", "narrator_validator")
    graph.add_conditional_edges(
        "narrator_validator",
        route_after_narrator_validation,
        {
            "pass": "result_aggregator",
            "fail": "template_fallback",
        },
    )
    graph.add_edge("template_fallback", "result_aggregator")

    # ===== 反思循环（报告生成）=====
    # 【面试知识点】Reflection 是 Agent 的高级模式：
    # 生成 → 评估 → 优化 → 输出，最多优化 1 次防止死循环
    graph.add_edge("report_generator", "report_evaluator")
    graph.add_conditional_edges(
        "report_evaluator",
        route_after_evaluation,
        {
            "pass": "result_aggregator",
            "refine": "report_generator",  # 最多优化 1 次
        },
    )

    # 批量/知识/降级 → 结果聚合
    graph.add_edge("batch_dispatcher", "result_aggregator")
    graph.add_edge("knowledge_qa", "result_aggregator")
    graph.add_edge("degradation_handler", "result_aggregator")

    # 结果 → 结束
    graph.add_edge("result_aggregator", END)

    # ===== 编译图（带检查点器）=====
    checkpointer = _create_checkpointer()

    return graph.compile(checkpointer=checkpointer)


class _LazyAsyncSqliteSaver:
    """懒加载的异步 SQLite 检查点器。

    【设计意图】
    AsyncSqliteSaver.__init__ 会调用 asyncio.get_running_loop()，
    但图可能在同步代码中编译（此时没有事件循环）。
    另外，立即创建 aiosqlite.Connection 会启动后台线程，
    导致测试套件无法正常退出。

    【解决方案】
    本工厂类创建一个「空壳」检查点器，延迟到首次异步操作时才：
    - 绑定事件循环
    - 创建数据库连接

    【面试知识点】
    这是典型的「懒加载」模式，常用于：
    - 资源密集型对象的延迟初始化
    - 避免循环依赖
    - 测试环境中的 Mock 友好设计
    """

    @staticmethod
    def create(db_path: str):
        """创建异步 SQLite 检查点器，无需事件循环。

        【参数说明】
            db_path: SQLite 数据库文件路径

        【返回值】
            懒加载的 AsyncSqliteSaver 实例
        """
        import asyncio

        from langgraph.checkpoint.base import BaseCheckpointSaver
        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # 绕过 AsyncSqliteSaver.__init__，因为它会调用 asyncio.get_running_loop()
        saver = AsyncSqliteSaver.__new__(AsyncSqliteSaver)
        # 复制 __init__ 的逻辑，但跳过 get_running_loop() 调用
        BaseCheckpointSaver.__init__(saver)
        saver.jsonplus_serde = JsonPlusSerializer()
        # 存储 db_path，延迟到首次 setup() 时才创建连接
        saver._db_path = db_path
        saver.conn = None  # 懒加载 —— 首次 setup() 时创建
        saver.lock = asyncio.Lock()
        saver.loop = None  # 延迟绑定 —— 纯异步使用场景不需要
        saver.is_setup = False

        # 重写 setup() 方法，在父类 setup 前创建真实连接
        _original_setup = saver.setup

        async def _lazy_setup():
            if saver.conn is None:
                import aiosqlite

                saver.conn = await aiosqlite.connect(db_path)
            await _original_setup()

        saver.setup = _lazy_setup  # type: ignore[assignment]
        return saver


def _create_checkpointer():
    """创建检查点器，用于对话状态持久化。

    【功能说明】
    检查点器（Checkpointer）是 LangGraph 的核心组件，用于：
    - 持久化对话状态，支持进程重启后恢复
    - 实现多轮对话（用户追问时能获取上下文）
    - 支持人机交互（Human-in-the-loop）

    【降级策略】
    优先使用 AsyncSqliteSaver（异步持久化）→ 兆底到 MemorySaver（仅内存）

    【面试知识点】
    - AsyncSqliteSaver 适合异步服务，生产环境可换成 PostgresSaver
    - MemorySaver 在进程退出后状态丢失，仅适合开发测试
    - 懒加载设计避免测试环境中后台线程泄漏
    """
    try:
        import aiosqlite  # noqa: F401

        logger.info(f"[Graph] Using AsyncSqliteSaver checkpointer ({CHECKPOINT_DB})")
        return _LazyAsyncSqliteSaver.create(CHECKPOINT_DB)
    except ImportError:
        logger.warning("[Graph] aiosqlite / langgraph-checkpoint-sqlite missing, " "falling back to MemorySaver")
    except Exception as e:
        logger.warning(f"[Graph] AsyncSqliteSaver init failed ({e}), " "falling back to MemorySaver")

    try:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    except ImportError:
        logger.warning("[Graph] No checkpointer available")
        return None


# =============================================================================
# 模块级图实例（懒加载单例）
# =============================================================================

# 全局图实例，首次调用 get_graph() 时创建
_graph_instance = None


def get_graph():
    """获取或创建主图实例（单例模式）。

    【功能说明】
    使用懒加载确保图只在首次请求时创建，避免启动时开销。
    后续调用直接返回缓存的实例。

    【返回值】
        编译后的 StateGraph 实例
    """
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = build_main_graph()
    return _graph_instance
