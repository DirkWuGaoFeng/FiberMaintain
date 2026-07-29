"""告警类 Tools（data-collector）。"""
from src.tools.registry import tool
from src.mcp import backend

@tool(name="alarm_query", tags=["alarm"])
async def alarm_query(board_id: int | None = None,
                      port_id: int | None = None) -> dict:
    """查询当前活跃告警，可按单盘/端口过滤。
    注意：此工具不接受 fiber_id 参数！需先通过拓扑查询获取 board_id/port_id。

    Args:
        board_id: 单盘 ID（可选，需先从拓扑结果获取）
        port_id: 端口 ID（可选，需先从拓扑结果获取）
    """
    return await backend.get_alarms(board_id, port_id)