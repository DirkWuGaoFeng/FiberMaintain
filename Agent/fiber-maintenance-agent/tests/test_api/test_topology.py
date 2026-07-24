"""拓扑接口测试。"""
import pytest, httpx

BASE = "http://localhost:8080"

@pytest.mark.asyncio
async def test_get_fiber_normal(client):
    r = await client.get("/api/v1/topology/fibers/1001")
    assert r.status_code == 200
    data = r.json()
    assert "fiber_id" in data or "data" in data

@pytest.mark.asyncio
async def test_get_fiber_not_found(client):
    r = await client.get("/api/v1/topology/fibers/999999")
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_batch_fibers_normal(client):
    r = await client.post("/api/v1/topology/fibers/batch",
                          json={"fiber_ids": [1001, 1002, 1003]})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_batch_fibers_over_limit(client):
    ids = list(range(1, 102))  # 101 条 > 100
    r = await client.post("/api/v1/topology/fibers/batch",
                          json={"fiber_ids": ids})
    assert r.status_code in (400, 422)

@pytest.mark.asyncio
async def test_get_board(client):
    r = await client.get("/api/v1/boards/101")
    assert r.status_code in (200, 404)