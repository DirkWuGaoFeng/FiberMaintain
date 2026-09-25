#!/usr/bin/env python3
"""快速 SSE 流验证脚本。"""

import json
import sys
import time
from collections import Counter

import httpx

sys.stdout.reconfigure(encoding="utf-8")

AGENT = "http://localhost:8000"
QUERY = "查询光纤 3 的跨段衰耗"

print(f"SSE Stream Test: {QUERY}")
print("=" * 60)

start = time.time()
events = []
final_output = ""

try:
    with httpx.stream(
        "POST",
        f"{AGENT}/fiber-agent/stream",
        json={
            "input": {
                "messages": [{"role": "user", "content": QUERY}],
                "thread_id": f"sse-verify-{int(time.time())}",
                "user_input": QUERY,
            },
            "config": {"configurable": {"thread_id": f"sse-verify-{int(time.time())}"}},
            "stream_mode": "events",
        },
        timeout=30,
    ) as resp:
        ct = resp.headers.get("content-type", "?")
        print(f"HTTP {resp.status_code} | Content-Type: {ct}")
        print("-" * 60)

        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                if not block.strip():
                    continue
                data_str = ""
                for line in block.split("\n"):
                    if line.startswith("data: "):
                        data_str += line[6:]
                if not data_str or data_str == "[DONE]":
                    continue
                try:
                    ev = json.loads(data_str)
                    etype = ev.get("event", "?")
                    ename = ev.get("name", "")
                    events.append(etype)
                    elapsed = round((time.time() - start) * 1000)

                    if etype == "final_output":
                        final_output = ev.get("data", {}).get("output", "")
                        print(f"[{elapsed:>6}ms] FINAL_OUTPUT: {final_output[:80]}")
                    elif etype in ("on_chain_start", "on_chain_end") and ename:
                        print(f"[{elapsed:>6}ms] {etype}: {ename}")
                    elif etype == "heartbeat":
                        hb = ev.get("data", {}).get("elapsed_ms", 0)
                        print(f"[{elapsed:>6}ms] heartbeat (elapsed={hb}ms)")
                    elif etype == "error":
                        msg = ev.get("data", {}).get("message", "")
                        print(f"[{elapsed:>6}ms] ERROR: {msg}")
                except json.JSONDecodeError:
                    pass

    total_ms = round((time.time() - start) * 1000)
    print("-" * 60)
    print(f"Total events: {len(events)}")
    for k, v in Counter(events).most_common():
        print(f"  {k}: {v}")
    print(f"\nFinal output received: {bool(final_output)}")
    if final_output:
        print(f"Content: {final_output}")
    print(f"Total time: {total_ms}ms")
    print(f"\nRESULT: {'PASS' if final_output else 'FAIL'}")

except httpx.ConnectError:
    print("FAIL: Cannot connect to Agent (localhost:8000)")
except httpx.TimeoutException:
    print("FAIL: SSE stream timeout")
except Exception as e:
    print(f"FAIL: {e}")
