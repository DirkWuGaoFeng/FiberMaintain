"""
提示词加载器：从 prompts/ 目录加载提示词模板，支持版本管理。

提示词按子智能体分目录组织：
  prompts/lead_agent/          - 意图分类器、任务分解器、结果聚合器
  prompts/data_collector/      - 数据收集器系统提示词
  prompts/analysis_expert/     - 分析专家系统提示词 + 少样本示例
  prompts/report_generator/    - 报告生成系统提示词 + 模板
  prompts/knowledge_assistant/ - 知识问答系统提示词

【面试知识点】
  - 提示词与代码分离是工业级 Agent 的基本实践，便于热更新和版本管理
  - fallback 机制确保即使提示词文件缺失，系统也能降级运行
"""

from __future__ import annotations

import re
from pathlib import Path

# 提示词根目录
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# HTML 注释块（提示词文件内的编写说明，不发给 LLM）
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def load_prompt(sub_agent: str, name: str, default: str = "") -> str:
    """从 prompts/ 目录加载提示词模板文件。

    【功能说明】
    根据子智能体名称和提示词文件名，从 prompts/ 目录加载对应的 .md 模板。
    加载时自动剔除 HTML 注释块（<!-- ... -->），确保注释不会发送给 LLM。

    【参数说明】
        sub_agent: 子智能体目录名，如 'lead_agent'、'analysis_expert'
        name: 提示词文件名（不含 .md 后缀），如 'intent_classifier'、'system'
        default: 文件未找到时返回的兜底内容

    【返回值】
        去除 HTML 注释后的提示词内容字符串

    【面试知识点】
    - 提示词即代码（Prompt as Code），与源码分离便于独立版本管理和热更新
    - HTML 注释块是提示词工程师的编写备注，不应发送给 LLM 以节省 token
    """
    prompt_path = PROMPTS_DIR / sub_agent / f"{name}.md"
    if prompt_path.exists():
        text = prompt_path.read_text(encoding="utf-8")
        return _HTML_COMMENT_RE.sub("", text).strip()
    return default


def escape_for_template(text: str, keep_vars: tuple[str, ...] = ()) -> str:
    """为 ChatPromptTemplate 转义字面花括号，保留指定模板变量。

    【功能说明】
    LangChain 的 ChatPromptTemplate 使用 {variable} 语法做模板变量。
    但提示词中的 JSON 示例也使用花括号，会被误认为模板变量。
    本函数将所有花括号双写转义（{ → {{），然后恢复指定的模板变量。

    【参数说明】
        text: 原始提示词文本
        keep_vars: 需要保留为模板变量的名称元组，如 ("loop_count", "max_loops")

    【返回值】
        转义后的文本，字面花括号已双写，指定变量保持单花括号

    【示例】
        escape_for_template('{"key": {val}}', keep_vars=('val',))
        → '{{"key": {val}}}'
    """
    escaped = text.replace("{", "{{").replace("}", "}}")
    for var in keep_vars:
        escaped = escaped.replace("{{" + var + "}}", "{" + var + "}")
    return escaped


# =============================================================================
# 默认提示词（当 prompts/ 目录下的文件未找到时，作为兆底使用）
# =============================================================================

INTENT_CLASSIFIER_PROMPT = """你是光纤维护系统的意图识别器。根据用户输入识别意图并提取关键参数。
光纤ID格式：FIB-XXXX（4位数字编号，如 FIB-0001）。
仅输出 JSON，不需要解释。"""

RESULT_AGGREGATOR_PROMPT = """你是光纤维护智能体系统的结果聚合器，负责将各子图的执行结果整合为用户友好的最终回复。
将分析结果总结为清晰、可操作的自然语言回复。
使用 Markdown 格式提升可读性。
包含具体的光纤ID、测量数据和建议措施。"""

DATA_COLLECTOR_SYSTEM_PROMPT = """你是光纤维护智能体系统中的数据收集专家。
你的职责是通过调用合适的工具收集光纤数据。
工作原则：
1. 调用前验证光纤ID是否为 FIB-XXXX 格式。
2. 收集所有相关数据（拓扑、性能、跨段损耗、告警）。
3. 原样返回后端数据，不做二次解读（分析由其他智能体完成）。
4. 如果某个查询失败，记录错误但继续执行其他查询。"""

ANALYSIS_SYSTEM_PROMPT = """你是光纤维护智能体系统中的分析专家。
分析光纤数据的以下方面：
- 跨段损耗异常（阈值：>0.5dB 异常，>1.0dB 严重）
- 颜色状态（GREEN=正常，YELLOW=告警，RED=严重）
- 性能趋势（OOP/IOP 偏差）
- 告警关联分析

输出带严重程度的结构化结论。
精确且基于数据，绝不编造数据。"""

REPORT_SYSTEM_PROMPT = """你是光纤维护智能体系统中的报告生成专家。
生成 Markdown 格式的专业维护报告。
报告应包含：
1. 概要总结
2. 详细发现（含数据表格）
3. 风险评估
4. 建议措施（按优先级排列）
5. 数据附录（原始数据引用）"""

KNOWLEDGE_SYSTEM_PROMPT = """你是光纤维护智能体系统中的知识问答助手。
基于光纤维护知识库回答用户问题。
尽可能标注信息来源。
如果知识库中没有相关信息，明确告知用户。"""
