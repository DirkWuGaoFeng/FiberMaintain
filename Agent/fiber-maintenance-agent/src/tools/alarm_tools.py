"""告警类 Tools（data-collector）。"""
from src.tools.registry import tool
from src.mcp import backend

@tool(name="alarm_query", tags=["alarm"])
async def alarm_query(board_id: int | None = None,
                      port_id: int | None = None) -> dict:
    """查询当前活跃告警，可按单盘/端口过滤。

    Args:
        board_id: 单盘 ID（可选）
        port_id: 端口 ID（可选）
    """
    return await backend.get_alarms(board_id, port_id)