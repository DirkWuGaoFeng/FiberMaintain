"""示例 Tool 插件：放入 plugins/tools/ 目录即自动注册，修改后 5s 内热加载。"""
from src.plugins.sdk import ToolPlugin
from src.tools.registry import Tool

async def _example_query(param: str) -> dict:
    """示例工具：回显参数。

    Args:
        param: 任意参数
    """
    return {"echo": param, "plugin": "example"}

class ExamplePlugin(ToolPlugin):
    name = "example"
    version = "1.0.0"
    description = "示例插件"
    author = "ops"

    def get_tools(self) -> list[Tool]:
        from src.tools.registry import _build_schema
        return [Tool(name="example_query",
                     description="示例工具：回显参数",
                     fn=_example_query,
                     schema=_build_schema(_example_query),
                     tags=["example"])]