#!/usr/bin/env python3
"""转储原始 SSE 响应以了解其格式。"""

import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8")

AGENT = "http://localhost:8000"
QUERY = "查询光纤 3 的跨段衰耗"

print(f"Raw SSE Dump: {QUERY}")
print("=" * 60)

start = time.time()
try:
    with httpx.stream(
        "POST",
        f"{AGENT}/fiber-agent/stream",
        json={
            "input": {
                "messages": [{"role": "user", "content": QUERY}],
                "thread_id": f"sse-raw-{int(time.time())}",
                "user_input": QUERY,
            },
            "config": {"configurable": {"thread_id": f"sse-raw-{int(time.time())}"}},
            "stream_mode": "events",
        },
        timeout=30,
    ) as resp:
        print(f"HTTP {resp.status_code}")
        print(f"Headers: {dict(resp.headers)}")
        print("-" * 60)

        count = 0
        for chunk in resp.iter_text():
            elapsed = round((time.time() - start) * 1000)
            # 打印每个数据块的前 500 个字符
            preview = chunk[:500].replace("\n", "\\n")
            print(f"[{elapsed}ms] CHUNK ({len(chunk)} chars): {preview}")
            count += 1
            if count > 20:
                print("... (truncated)")
                break

except Exception as e:
    print(f"Error: {e}")
