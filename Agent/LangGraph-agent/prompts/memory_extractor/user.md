<!--
用户记忆提取器 user 模板。模板变量：conversation / user_id
-->
## 对话内容
{conversation}

请提取该用户的长期记忆候选（结构化 JSON，最多 5 条）。
仅提取对话中明确出现或可靠推断的信息，不确定时 confidence 调低。
