<!--
分析专家 user 模板（v7.2 P0：书籍 Ch2 指令与数据分离）。
本段只承载系统可信数据：用户问题、程序化规则判断、已采集数据、循环历史、
任务上下文、安全提示、状态栏（状态栏由代码派生注入末尾，KV Cache 友好）。

外部低信任内容（经验 / RAG / 对话摘要）由 external.md 独立注入，
并带 <external_content> 来源标记，避免外部指令劫持（间接注入防御）。

模板变量：question / rule_judgment / data_summary / loop_history /
task_context / guard_notice / status_bar
-->
## 用户问题
{question}

## 规则判断（程序化，可信）
{rule_judgment}

## 已收集数据摘要
{data_summary}

## 循环历史
{loop_history}

## 任务上下文（系统维护，任务计划与进度）
{task_context}

## 安全提示（系统维护，若为空则为"无"）
{guard_notice}

## 当前执行状态（系统维护，请无条件信任）
{status_bar}
