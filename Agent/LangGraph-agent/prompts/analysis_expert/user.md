<!--
分析专家 human 模板（运行时上下文注入段）。
模板变量：question / rule_judgment / data_summary / loop_history /
experience_history / loop_count / max_loops / llm_calls / max_llm_calls
-->
## 用户问题
{question}

## 规则判断（程序化，可信）
{rule_judgment}

## 已收集数据摘要
{data_summary}

## 循环历史
{loop_history}

## 该光纤历史经验（确定性检索，仅供参考）
{experience_history}

## 状态: 第 {loop_count}/{max_loops} 轮, LLM调用 {llm_calls}/{max_llm_calls}
