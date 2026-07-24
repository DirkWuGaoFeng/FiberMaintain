"""pytest 共享 fixtures。"""
import asyncio, pytest, httpx

BACKEND_URL = "http://localhost:8080"
AGENT_URL = "http://localhost:8000"

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="session")
async def client():
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=10) as c:
        yield c

@pytest.fixture(scope="session")
async def agent_client():
    async with httpx.AsyncClient(base_url=AGENT_URL, timeout=60) as c:
        yield c