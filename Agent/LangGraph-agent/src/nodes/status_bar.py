"""
状态栏（Status Bar）—— 纯代码维护的显式状态块（书籍 Ch2 状态栏原则）。

【设计原则】
- 状态栏由代码确定性派生，不消耗 LLM，注入 user 消息末尾
  （不改 system prompt，保持前缀稳定，KV Cache 友好）
- 把隐式循环状态显式化：剩余预算、已请求工具、失败操作、停滞风险
- 模型对状态栏无条件信任：内容只来自 state 事实，不含推测

【架构位置】
  analysis_expert 节点 → build_status_bar(state) → user 消息末尾 {status_bar}

【面试知识点】
  Q: 为什么状态栏不用 LLM 生成？
  A: 状态栏的价值是"模型无条件信任的事实"。LLM 生成的状态本身
     可能出错，会引入新的幻觉源；纯代码派生则保证 100% 准确。
  Q: 状态栏如何帮助循环控制？
  A: 把失败工具清单和停滞警告显式注入后，LLM 不需要从冗长的
     数据摘要中自行推断"什么已经试过了"，降低重复请求相同数据
     的概率（无进展检测的第一道预防）。
"""

from __future__ import annotations

# collected_data_summary 的错误前缀（data_collector / fast_path_executor /
# batch_dispatcher 失败路径产出的摘要以此开头）
_ERROR_PREFIXES = ("数据采集失败", "查询失败")


def build_status_bar(state: dict) -> str:
    """从主图状态构建状态栏文本（纯代码，零 LLM）。

    【参数说明】
        state: MainGraphState 兼容的字典

    【返回值】
        多行状态文本，每行以 "- " 开头，直接注入提示词末尾
    """
    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)
    llm_calls = state.get("llm_call_count", 0)
    max_llm_calls = state.get("max_llm_calls", 10)
    no_progress = state.get("no_progress_count", 0)
    remaining = max(0, int(max_llm_calls) - int(llm_calls))

    lines = [
        f"- 循环进度: 第 {loop_count}/{max_loops} 轮, LLM 调用 {llm_calls}/{max_llm_calls}, "
        f"剩余预算 {remaining} 次",
    ]

    # 预算显式化（书籍 Ch2）：把剩余预算注入上下文，模型可据此主动停止，
    # 而非到耗尽才被 Harness 截停。
    if max_llm_calls > 0 and int(llm_calls) >= int(max_llm_calls * 0.75):
        if remaining > 0:
            lines.append(f"- ⚠ 预算紧张（剩 {remaining} 次 LLM 调用）: " "仅做最终小结，不再请求新的数据工具")
        else:
            lines.append("- ⚠ 预算已耗尽: 立即输出结论，禁止再调用工具")

    # 已请求过数据的工具（来自循环历史，保序去重）
    history = state.get("loop_history") or []
    tools: list[str] = []
    for record in history:
        tool = record.get("tool_requested")
        if tool and tool != "unknown" and tool not in tools:
            tools.append(tool)
    lines.append("- 已请求数据的工具: " + (", ".join(tools) if tools else "无"))

    # 已失败操作（审计日志中带 error 的条目）
    failures: list[str] = []
    for entry in state.get("audit_trail") or []:
        err = entry.get("error")
        if err:
            failures.append(f"{entry.get('node', 'unknown')}: {str(err)[:60]}")
    lines.append("- 已失败操作: " + ("; ".join(failures) if failures else "无"))

    # 降级工具统计（degraded 与 error 区分：degraded=部分成功，error=完全失败）
    # 从审计日志中统计 status="degraded" 的记录
    degraded_count = sum(1 for entry in state.get("audit_trail") or [] if entry.get("status") == "degraded")
    if degraded_count > 0:
        lines.append(
            f"- ⚠ 降级工具数: {degraded_count} 个工具返回了降级结果"
            "（部分数据可用，后端可能部分离线），建议换渠道或重试"
        )

    # 已收集数据状态
    summary = state.get("collected_data_summary")
    if not summary:
        lines.append("- 已收集数据: 尚未收集")
    elif str(summary).startswith(_ERROR_PREFIXES):
        lines.append(f"- 已收集数据: 采集失败（{str(summary)[:80]}）")
    else:
        lines.append(f"- 已收集数据: 可用（摘要 {len(str(summary))} 字符）")

    # 停滞风险预警（无进展检测的提示侧配合）
    if no_progress > 0:
        lines.append(
            f"- ⚠ 停滞警告: 已连续 {no_progress} 轮相同动作未获新信息，" "禁止重复相同查询，应直接基于现有数据输出结论"
        )

    return "\n".join(lines)
