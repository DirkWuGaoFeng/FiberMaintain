"""告警接口测试。"""
import pytest

@pytest.mark.asyncio
async def test_alarms_all(client):
    r = await client.get("/api/v1/alarms/current")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_alarms_by_board(client):
    r = await client.get("/api/v1/alarms/current", params={"board_id": 101})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_alarms_by_board_port(client):
    r = await client.get("/api/v1/alarms/current",
                         params={"board_id": 101, "port_id": 1})
    assert r.status_code == 200