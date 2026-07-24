"""模拟数据注入器：通过后端 API 注入测试数据。"""
import asyncio, httpx

BACKEND_URL = "http://localhost:8080"

class TestDataInjector:
    def __init__(self, base_url: str = BACKEND_URL):
        self.base_url = base_url
        self.client: httpx.AsyncClient | None = None
        self.created_fibers: list[int] = []

    async def setup(self):
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=10)

    async def teardown(self):
        if self.client:
            await self.client.aclose()

    async def inject_test_fibers(self, count: int = 10) -> list[int]:
        """创建测试连纤（需后端支持 POST 创建接口）。"""
        fiber_ids = []
        for i in range(count):
            payload = {
                "src_board_id": 100 + i,
                "src_port_id": 1,
                "src_ne_id": 1000 + i,
                "dst_board_id": 200 + i,
                "dst_port_id": 1,
                "dst_ne_id": 2000 + i,
            }
            try:
                r = await self.client.post("/api/v1/topology/fibers",
                                           json=payload)
                if r.status_code in (200, 201):
                    fid = r.json().get("fiber_id")
                    if fid:
                        fiber_ids.append(fid)
            except Exception:
                pass
        self.created_fibers = fiber_ids
        print(f"注入 {len(fiber_ids)} 条测试连纤")
        return fiber_ids

    async def inject_test_alarms(self, fiber_ids: list[int],
                                 level: str = "CRITICAL"):
        """注入测试告警。"""
        for fid in fiber_ids[:3]:
            try:
                await self.client.post("/api/v1/alarms", json={
                    "fiber_id": fid, "level": level,
                    "message": f"测试告警-{level}"
                })
            except Exception:
                pass
        print(f"注入 {min(len(fiber_ids), 3)} 条 {level} 告警")

    async def inject_test_performance(self, fiber_id: int,
                                      oop: float, iop: float):
        """注入测试性能数据。"""
        try:
            await self.client.post(f"/api/v1/fibers/{fiber_id}/performance",
                                   json={"src_oop": oop, "dst_iop": iop})
        except Exception:
            pass

    async def cleanup(self):
        """清理测试数据。"""
        for fid in self.created_fibers:
            try:
                await self.client.delete(f"/api/v1/topology/fibers/{fid}")
            except Exception:
                pass
        print(f"清理 {len(self.created_fibers)} 条测试连纤")


async def main():
    injector = TestDataInjector()
    await injector.setup()
    try:
        fids = await injector.inject_test_fibers(5)
        if fids:
            await injector.inject_test_alarms(fids, "CRITICAL")
            await injector.inject_test_performance(fids[0], -2.0, -15.0)
    finally:
        await injector.cleanup()
        await injector.teardown()

if __name__ == "__main__":
    asyncio.run(main())