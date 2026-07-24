"""颜色/统计/趋势接口测试。"""
import pytest
from datetime import datetime, timedelta, timezone

@pytest.mark.asyncio
async def test_colored_red(client):
    r = await client.get("/api/v1/fibers/colored", params={"color": "RED"})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_colored_yellow(client):
    r = await client.get("/api/v1/fibers/colored", params={"color": "YELLOW"})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_colored_invalid(client):
    r = await client.get("/api/v1/fibers/colored", params={"color": "BLUE"})
    assert r.status_code in (400, 422)

@pytest.mark.asyncio
async def test_all_colored(client):
    r = await client.get("/api/v1/fibers/colored/all")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_stats_realtime(client):
    r = await client.get("/api/v1/fibers/stats/realtime")
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_stats_trend(client):
    now = datetime.now(timezone.utc)
    start = (now - timedelta(hours=24)).isoformat()
    end = now.isoformat()
    r = await client.get("/api/v1/fibers/stats/trend",
                         params={"start_time": start, "end_time": end})
    assert r.status_code == 200

@pytest.mark.asyncio
async def test_stats_trend_invalid_range(client):
    r = await client.get("/api/v1/fibers/stats/trend",
                         params={"start_time": "invalid", "end_time": "invalid"})
    assert r.status_code in (400, 422, 500)