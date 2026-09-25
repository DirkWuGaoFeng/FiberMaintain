# -*- coding: utf-8 -*-
"""单例冒烟测试：验证主图端到端通路（意图→采集→叙述）"""

import asyncio
import sys
import time


async def main() -> None:
    t0 = time.monotonic()
    print(f"[{time.monotonic()-t0:.1f}s] 导入图...", flush=True)
    from src.graph.main_graph import get_graph
    from src.graph.state import create_initial_state

    g = get_graph()
    print(f"[{time.monotonic()-t0:.1f}s] 图编译完成，开始调用", flush=True)
    state = create_initial_state("查询光纤3的跨段损耗", "smoke-1")
    try:
        r = await asyncio.wait_for(
            g.ainvoke(state, {"configurable": {"thread_id": "smoke-1"}}),
            timeout=240,
        )
    except asyncio.TimeoutError:
        print(f"[{time.monotonic()-t0:.1f}s] !! ainvoke 超时（240s）", flush=True)
        sys.exit(2)
    print(f"[{time.monotonic()-t0:.1f}s] 完成", flush=True)
    print("intent:", r.get("intent"))
    print("path:", r.get("processing_path"))
    print("output:", (r.get("final_output") or "")[:300])


if __name__ == "__main__":
    asyncio.run(main())
