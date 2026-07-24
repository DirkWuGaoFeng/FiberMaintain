"""性能类 Tools（data-collector / analysis-expert）。"""
from src.tools.registry import tool
from src.mcp import backend

@tool(name="fiber_performance_query", tags=["performance"])
async def fiber_performance_query(fiber_id: int) -> dict:
    """查询光纤性能：源端输出光功率 OOP 与宿端输入光功率 IOP（dBm）。

    Args:
        fiber_id: 光纤连纤 ID
    """
    return await backend.get_performance(fiber_id)

@tool(name="fiber_spanloss_query", tags=["performance"])
async def fiber_spanloss_query(fiber_id: int) -> dict:
    """查询光纤衰耗值（dB）。衰耗由后端 C++ 服务计算，Agent 仅读取。

    Args:
        fiber_id: 光纤连纤 ID
    """
    return await backend.get_spanloss(fiber_id)