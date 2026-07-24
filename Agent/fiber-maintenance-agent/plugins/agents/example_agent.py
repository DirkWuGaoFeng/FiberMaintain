"""示例 Agent 插件：放入 plugins/agents/ 目录即自动注册，修改后 5s 内热加载。"""
from src.plugins.sdk import AgentPlugin

class ExampleAgentPlugin(AgentPlugin):
    name = "example-analyst"
    description = "示例分析 Agent 插件"
    model_profile = "fast"
    tools = ["fiber_performance_query", "colored_fibers_query"]
    system_prompt = """你是示例分析专家。职责：演示 Agent 插件机制。

约束：
- 仅做演示用途
- 返回结构化 JSON 摘要"""
