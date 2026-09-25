"""
任务上下文（Task Context）—— 纯代码派生的任务计划与进度（书籍 Ch2）。

【设计原则】
- 任务上下文由代码确定性派生，不消耗 LLM
- 把"当前任务是什么、做到哪了"显式注入上下文，避免模型从历史推断
- 内容只来自 state 事实（intent/params/audit_trail/loop_history），不含推测
- 与 status_bar 互补：status_bar 管"还剩多少资源"，task_context 管"做到哪了"

【架构位置】
  analysis_expert 节点 → build_task_context(state) → user 消息末尾
  {task_context} 在 {status_bar} 之前

【面试知识点】
  Q: 为什么需要 task_context 而不是让模型自己看历史？
  A: 模型从数十轮历史中推断"当前进度"容易遗漏或出错；
     显式注入把 O(n) 的隐式推断变成单步阅读，准确率更高。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 确定性步骤映射：字段名 → 步骤描述（计划与进度共用同一命名，保证匹配）
_STEP_DESCRIPTIONS: dict[str, str] = {
    "rule_match": "规则匹配",
    "intent_classified": "意图分类",
    "params_normalized": "参数归一化与验证",
    "data_collected": "数据采集",
    "rule_judged": "程序化判断",
    "analysis_completed": "LLM 分析评估",
    "narrator_output": "叙述生成",
    "narrator_validated": "叙述校验",
    "report_generated": "报告生成",
    "report_evaluated": "报告评估",
    "batch_dispatched": "批量文件分发",
    "knowledge_qa": "知识库问答",
    "template_fallback": "模板降级输出",
    "result_aggregated": "结果聚合",
}

# 计划步骤别名 → 标准步骤名（用于意图计划与进度命名的对齐）
_PLAN_STEP_ALIASES: dict[str, str] = {
    "参数验证": "参数归一化与验证",
    "快速查询": "规则匹配",
    "批量分发": "批量文件分发",
    "LLM 分析": "LLM 分析评估",
    "诊断分析": "LLM 分析评估",
    "趋势分析": "LLM 分析评估",
    "健康评估": "LLM 分析评估",
    "结果聚合": "结果聚合",
    "直接输出": "结果聚合",
    "RAG 检索": "知识库问答",
    "知识问答": "知识库问答",
    "社交对话": "意图分类",
}


def _normalize_step(name: str) -> str:
    """把计划中的步骤名归一化为标准步骤名（用于与进度匹配）。"""
    return _PLAN_STEP_ALIASES.get(name, name)


def _derive_task_plan(state: dict) -> str:
    """从 state 派生任务计划（纯代码，零 LLM）。

    【输出示例】
      "任务：分析光纤5的衰耗趋势（batch_query），
       计划：参数归一化与验证 → 数据采集 → 规则判断 → LLM 分析评估 → 叙述生成"
    """
    intent = state.get("intent") or "未知"
    user_input = state.get("user_input", "")

    # 从 normalized_params 提取关键实体
    params = state.get("normalized_params") or {}
    entities = []
    if params.get("fiber_ids"):
        entities.append(f"光纤{params['fiber_ids']}")
    if params.get("board_ids"):
        entities.append(f"板卡{params['board_ids']}")
    if params.get("port_ids"):
        entities.append(f"端口{params['port_ids']}")
    if params.get("color"):
        entities.append(f"颜色={params['color']}")

    # 意图 → 计划描述（使用标准步骤名，保证与进度可匹配）
    intent_plan_map: dict[str, str] = {
        "single_query": "参数归一化与验证 → 规则匹配 → 结果聚合",
        "batch_query": "参数归一化与验证 → 批量文件分发 → 结果聚合",
        "spanloss_analysis": "参数归一化与验证 → 数据采集 → 程序化判断 → LLM 分析评估 → 叙述生成",
        "color_diagnosis": "参数归一化与验证 → 数据采集 → 程序化判断 → LLM 分析评估 → 叙述生成",
        "trend_analysis": "参数归一化与验证 → 数据采集 → 程序化判断 → LLM 分析评估 → 叙述生成",
        "health_check": "参数归一化与验证 → 数据采集 → 程序化判断 → LLM 分析评估 → 叙述生成",
        "report_generation": "参数归一化与验证 → 数据采集 → 报告生成 → 报告评估",
        "knowledge_qa": "知识库问答",
        "chitchat": "意图分类 → 结果聚合",
    }
    plan = intent_plan_map.get(intent, "意图分类 → 数据采集 → LLM 分析评估 → 结果聚合")

    entity_desc = "，".join(entities) if entities else ""
    if entity_desc:
        return f"任务：分析{entity_desc}（{intent}），计划：{plan}"
    # 用 user_input 前 30 字作为任务描述
    task_desc = user_input[:30] + ("..." if len(user_input) > 30 else "")
    return f"任务：{task_desc}（{intent}），计划：{plan}"


def _derive_completed_steps(state: dict) -> list[str]:
    """从 state 派生已完成步骤列表（纯代码，零 LLM）。

    检查 state 中各字段是否非空，结合 audit_trail 中的节点执行记录。
    """
    completed: list[str] = []

    # 检查确定性字段
    field_checks = [
        ("rule_match", "rule_match"),
        ("intent", "intent_classified"),
        ("normalized_params", "params_normalized"),
        ("collected_data_summary", "data_collected"),
        ("rule_judgment", "rule_judged"),
        ("analysis_verdict", "analysis_completed"),
        ("narration", "narrator_output"),
        ("narrator_validation_passed", "narrator_validated"),
        ("report_content", "report_generated"),
        ("report_eval", "report_evaluated"),
    ]
    for field, step_key in field_checks:
        if state.get(field):
            desc = _STEP_DESCRIPTIONS.get(step_key, step_key)
            if desc not in completed:
                completed.append(desc)

    # 补充：从 audit_trail 中提取已完成的节点
    for entry in state.get("audit_trail") or []:
        node = entry.get("node", "")
        success = entry.get("status") in ("completed", "success")
        if success and node:
            desc = _STEP_DESCRIPTIONS.get(node, node)
            if desc not in completed:
                completed.append(desc)

    # 确定性的顺序修正
    _ORDER = [
        "规则匹配",
        "意图分类",
        "参数归一化与验证",
        "数据采集",
        "程序化判断",
        "LLM 分析评估",
        "叙述生成",
        "叙述校验",
        "报告生成",
        "报告评估",
        "批量文件分发",
        "知识库问答",
        "模板降级输出",
        "结果聚合",
    ]
    completed.sort(key=lambda x: _ORDER.index(x) if x in _ORDER else 999)

    return completed


def build_task_context(state: dict) -> str:
    """构建任务上下文文本（纯代码，零 LLM）。

    【参数说明】
        state: MainGraphState 兼容的字典

    【返回值】
        多行文本，每行以 "- " 开头，直接注入提示词 {task_context} 位置
    """
    plan = state.get("task_plan") or _derive_task_plan(state)
    progress = state.get("task_progress") or _derive_completed_steps(state)

    lines = [
        f"- 任务计划: {plan}",
        "- 已完成步骤: " + (" → ".join(progress) if progress else "尚未开始"),
        "- 下一步: " + _derive_next_step(plan, progress),
    ]
    return "\n".join(lines)


def _derive_next_step(plan: str, completed: list[str]) -> str:
    """从计划与已完成步骤推断下一步（纯文本匹配，零 LLM）。"""
    # 从 plan 中提取"计划："之后的步骤序列（排除"任务："前缀）
    if "计划：" in plan:
        plan_tail = plan.split("计划：", 1)[1]
    else:
        plan_tail = plan
    plan_steps = [_normalize_step(s.strip()) for s in plan_tail.split("→") if s.strip()]
    if not plan_steps:
        return "等待执行"

    # 找到第一个未完成的计划步骤
    for step in plan_steps:
        if step not in completed:
            return step
    return "全部完成，等待结果聚合"
