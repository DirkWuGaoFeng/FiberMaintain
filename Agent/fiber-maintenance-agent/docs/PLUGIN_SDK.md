# 插件开发指南（Plugin SDK）

## 概述

光纤维护 Agent 支持两类插件：
- **Tool 插件**：扩展可用工具（放入 `plugins/tools/`）
- **Agent 插件**：扩展子智能体（放入 `plugins/agents/`）

插件支持**热加载**：修改文件后 5 秒内自动生效，无需重启服务。

## Tool 插件开发

### 1. 创建文件

```python
# plugins/tools/my_tool.py
from src.plugins.sdk import ToolPlugin
from src.tools.registry import Tool, _build_schema

async def my_query(param: str) -> dict:
    """我的自定义工具。

    Args:
        param: 参数说明
    """
    return {"result": f"处理了 {param}"}

class MyPlugin(ToolPlugin):
    name = "my_plugin"
    version = "1.0.0"
    description = "示例插件"
    author = "your_name"

    def get_tools(self) -> list[Tool]:
        return [Tool(
            name="my_query",
            description="我的自定义工具",
            fn=my_query,
            schema=_build_schema(my_query),
            tags=["custom"],
        )]