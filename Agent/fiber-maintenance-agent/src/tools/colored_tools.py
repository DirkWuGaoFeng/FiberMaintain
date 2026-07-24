"""颜色类 Tools（data-collector / analysis-expert）。颜色由后端判定。"""
from src.tools.registry import tool
from src.mcp import backend

@tool(name="colored_fibers_query", tags=["color"])
async def colored_fibers_query(color: str) -> dict:
    """按颜色查询有颜色连纤列表（含后端判定的场景类型与情况分类）。

    Args:
        color: 颜色，RED（紧急）或 YELLOW（次要）
    """
    return await backend.get_colored(color)

@tool(name="all_colored_fibers_query", tags=["color"])
async def all_colored_fibers_query() -> dict:
    """查询全部有颜色连纤（红+黄）。"""
    return await backend.get_all_colored()