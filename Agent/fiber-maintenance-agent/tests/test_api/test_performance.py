"""性能/衰耗接口测试。"""
import pytest

@pytest.mark.asyncio
async def test_performance_normal(client):
    r = await client.get("/api/v1/fibers/1001/performance")
    assert r.status_code == 200
    data = r.json()
    d = data.get("data", data)
    assert "src_oop" in d or "oop" in d or "fiber_id" in d

@pytest.mark.asyncio
async def test_performance_not_found(client):
    r = await client.get("/api/v1/fibers/999999/performance")
    assert r.status_code == 404

@pytest.mark.asyncio
async def test_spanloss_normal(client):
    r = await client.get("/api/v1/fibers/1001/spanloss")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_spanloss_not_found(client):
    r = await client.get("/api/v1/fibers/999999/spanloss")
    assert r.status_code == 404