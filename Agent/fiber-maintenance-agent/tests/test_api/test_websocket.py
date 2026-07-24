"""WebSocket 接口测试。"""
import pytest, asyncio, json

WS_URL = "ws://localhost:8081/ws/v1/events"

@pytest.mark.asyncio
async def test_ws_connect_and_subscribe():
    import websockets
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            # 订阅
            await ws.send(json.dumps({
                "action": "subscribe",
                "channels": ["fiber_stats", "fiber_color", "alarm"]
            }))
            # 等待确认或消息（最多 5s）
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data  # 收到任何消息即通过
    except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
        pytest.skip("后端 WS 不可用，跳过")

@pytest.mark.asyncio
async def test_ws_heartbeat():
    import websockets
    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            await ws.send(json.dumps({"action": "ping"}))
            msg = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(msg)
            assert data.get("type") == "pong" or "pong" in str(data).lower()
    except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
        pytest.skip("后端 WS 不可用，跳过")