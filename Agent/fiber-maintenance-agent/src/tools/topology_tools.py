"""拓扑类 Tools（topology-analyst）。"""
from src.tools.registry import tool
from src.mcp import backend

@tool(name="fiber_connection_query", tags=["topology"])
async def fiber_connection_query(fiber_id: int) -> dict:
    """查询单条连纤的连接信息（源/宿单盘、端口、网元）。

    Args:
        fiber_id: 光纤连纤 ID（int32）
    """
    return await backend.get_fiber(fiber_id)

@tool(name="batch_fiber_connection_query", tags=["topology"])
async def batch_fiber_connection_query(fiber_ids: list[int]) -> dict:
    """批量查询连纤连接信息，单次最大 100 条。

    Args:
        fiber_ids: 连纤 ID 列表（≤100）
    """
    return await backend.batch_fibers(fiber_ids)

@tool(name="board_query", tags=["topology"])
async def board_query(board_id: int) -> dict:
    """查询单盘信息（含有源/无源类型、端口列表、所属网元）。

    Args:
        board_id: 单盘 ID
    """
    return await backend.get_board(board_id)

@tool(name="ne_query", tags=["topology"])
async def ne_query(board_id: int) -> dict:
    """通过单盘查询其所属网元信息。

    Args:
        board_id: 单盘 ID
    """
    board = await backend.get_board(board_id)
    return {"ne_id": board.get("ne_id"), "ne_name": board.get("ne_name"),
            "board_id": board_id}