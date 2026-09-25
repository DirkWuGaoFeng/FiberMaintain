#!/usr/bin/env python3
"""
端到端调试脚本 — 发送测试请求并打印完整执行链路。

Usage:
    python scripts/debug_trace.py "查询光纤 3 的跨段衰耗"
    python scripts/debug_trace.py --check   # 仅做环境预检

功能:
    1. 预检 Ollama (localhost:11434) 是否可达
    2. 预检 C++ 后端 (localhost:8080) 是否可达
    3. 预检 Agent (localhost:8000) 是否可达
    4. 调用 /invoke 同步端点发送测试请求
    5. 打印完整执行链路（各节点耗时、状态）
    6. 失败时给出具体诊断建议
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

# =============================================================================
# 配置
# =============================================================================

AGENT_BASE = "http://localhost:8000"
CPP_BACKEND_BASE = "http://localhost:8080"
OLLAMA_BASE = "http://localhost:11434"

# 默认测试查询
DEFAULT_QUERY = "查询光纤 3 的跨段衰耗"

# 超时配置
PREFLIGHT_TIMEOUT = 5.0  # 预检超时
INVOKE_TIMEOUT = 90.0  # 请求超时（比后端60s多留余量）


# =============================================================================
# 预检检查
# =============================================================================


def check_service(name: str, url: str, timeout: float = PREFLIGHT_TIMEOUT) -> dict:
    """检查服务是否可达，返回状态字典。"""
    start = time.time()
    try:
        resp = httpx.get(url, timeout=timeout)
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {
            "name": name,
            "status": "ok",
            "latency_ms": elapsed_ms,
            "http_status": resp.status_code,
            "detail": resp.text[:200] if resp.status_code == 200 else resp.text[:500],
        }
    except httpx.ConnectError:
        return {
            "name": name,
            "status": "unreachable",
            "latency_ms": round((time.time() - start) * 1000, 1),
            "detail": "Connection refused — 服务未启动或端口不正确",
        }
    except httpx.TimeoutException:
        return {
            "name": name,
            "status": "timeout",
            "latency_ms": round((time.time() - start) * 1000, 1),
            "detail": f"连接超时 ({timeout}s)",
        }
    except Exception as e:
        return {
            "name": name,
            "status": "error",
            "latency_ms": round((time.time() - start) * 1000, 1),
            "detail": str(e),
        }


def check_ollama_models() -> list[str]:
    """获取 Ollama 已安装模型列表。"""
    try:
        resp = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=PREFLIGHT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        pass
    return []


def run_preflight() -> bool:
    """执行环境预检，打印结果，返回是否全部通过。"""
    print("=" * 60)
    print("  🔍 环境预检 (Preflight Check)")
    print("=" * 60)

    checks = [
        ("Agent (FastAPI)", f"{AGENT_BASE}/health"),
        ("C++ Backend (API Gateway)", f"{CPP_BACKEND_BASE}/health"),
        ("Ollama (LLM)", f"{OLLAMA_BASE}/api/tags"),
    ]

    all_ok = True
    for name, url in checks:
        result = check_service(name, url)
        status_icon = "✅" if result["status"] == "ok" else "❌"
        print(f"\n  {status_icon} {result['name']}")
        print(f"     URL: {url}")
        print(f"     Status: {result['status']} | Latency: {result['latency_ms']}ms")

        if result["status"] != "ok":
            all_ok = False
            print(f"     ⚠️  {result['detail']}")
            _print_diagnosis(result["name"], result["status"])
        elif result.get("detail"):
            # 显示简要响应
            detail = result["detail"][:100]
            print(f"     Response: {detail}")

    # Ollama 模型列表
    models = check_ollama_models()
    if models:
        print(f"\n  📦 Ollama 已安装模型: {', '.join(models)}")
    elif all_ok:
        print("\n  ⚠️  Ollama 可达但未检测到模型")

    print("\n" + "=" * 60)
    if all_ok:
        print("  ✅ 所有服务正常，可以发送测试请求")
    else:
        print("  ⚠️  部分服务不可用，测试请求可能失败")
    print("=" * 60)

    return all_ok


def _print_diagnosis(service_name: str, status: str):
    """根据服务名和状态给出诊断建议。"""
    suggestions = {
        "Agent (FastAPI)": {
            "unreachable": [
                "确认 Agent 已启动: cd Agent/LangGraph-agent && python -m uvicorn src.server:app --port 8000",
                "检查端口 8000 是否被占用: netstat -ano | findstr :8000",
            ],
            "timeout": ["Agent 可能正在初始化，等待几秒后重试"],
        },
        "C++ Backend (API Gateway)": {
            "unreachable": [
                "确认 C++ 后端已编译并启动: ./build/api_gateway",
                "检查端口 8080 是否被占用: netstat -ano | findstr :8080",
                "WSL 下运行时需要确保网络互通",
            ],
            "timeout": ["C++ 后端可能正在初始化 gRPC 连接"],
        },
        "Ollama (LLM)": {
            "unreachable": [
                "确认 Ollama 已启动: ollama serve",
                "安装 Ollama: https://ollama.ai",
                "注意: 如果只使用快速路径(规则引擎命中)，Ollama 不是必须的",
            ],
            "timeout": ["Ollama 可能正在加载模型，等待几秒后重试"],
        },
    }

    service_suggestions = suggestions.get(service_name, {})
    for s in service_suggestions.get(status, []):
        print(f"     💡 {s}")


# =============================================================================
# Invoke 测试
# =============================================================================


def invoke_test(query: str) -> dict:
    """调用 Agent /invoke 端点并返回结果。"""
    print(f"\n{'=' * 60}")
    print("  🚀 发送测试请求")
    print(f"{'=' * 60}")
    print(f'  Query: "{query}"')
    print(f"  Endpoint: POST {AGENT_BASE}/invoke")
    print(f"  Timeout: {INVOKE_TIMEOUT}s")
    print(f"{'─' * 60}")

    start = time.time()
    try:
        resp = httpx.post(
            f"{AGENT_BASE}/invoke",
            json={"message": query, "thread_id": f"debug-{int(time.time())}"},
            timeout=INVOKE_TIMEOUT,
        )
        elapsed_ms = round((time.time() - start) * 1000, 1)

        if resp.status_code == 200:
            data = resp.json()
            print("\n  ✅ 请求成功")
            print(f"     总耗时: {elapsed_ms}ms")
            print(f"     处理路径: {data.get('processing_path', 'unknown')}")
            print(f"     Request ID: {data.get('request_id', 'N/A')}")
            print(f"     服务端耗时: {data.get('latency_ms', 'N/A')}ms")
            print("\n  📝 输出:")
            print(f"     {data.get('result', '(empty)')}")
            return {"success": True, "data": data, "elapsed_ms": elapsed_ms}
        else:
            print(f"\n  ❌ HTTP {resp.status_code}")
            print(f"     耗时: {elapsed_ms}ms")
            print(f"     响应: {resp.text[:500]}")
            return {"success": False, "error": f"HTTP {resp.status_code}", "elapsed_ms": elapsed_ms}

    except httpx.TimeoutException:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        print(f"\n  ❌ 请求超时 ({INVOKE_TIMEOUT}s)")
        print(f"     耗时: {elapsed_ms}ms")
        print("\n  💡 诊断建议:")
        print("     - 查询可能走了 LLM 路径（规则引擎未命中）且 Ollama 不可用")
        print("     - 检查 Agent 日志中的 [TRACE:xxx] 行确认卡在哪个节点")
        print("     - 尝试: python scripts/debug_trace.py --check 确认服务状态")
        return {"success": False, "error": "timeout", "elapsed_ms": elapsed_ms}

    except httpx.ConnectError:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        print("\n  ❌ 无法连接到 Agent (localhost:8000)")
        print(f"     耗时: {elapsed_ms}ms")
        print("     💡 确认 Agent 已启动: python -m uvicorn src.server:app --port 8000")
        return {"success": False, "error": "connect_error", "elapsed_ms": elapsed_ms}

    except Exception as e:
        elapsed_ms = round((time.time() - start) * 1000, 1)
        print(f"\n  ❌ 未知错误: {e}")
        print(f"     耗时: {elapsed_ms}ms")
        return {"success": False, "error": str(e), "elapsed_ms": elapsed_ms}


# =============================================================================
# SSE 流测试
# =============================================================================


def sse_test(query: str) -> dict:
    """测试 SSE 流端点，验证事件流和 final_output 事件。"""
    print(f"\n{'=' * 60}")
    print("  📡 SSE 流测试")
    print(f"{'=' * 60}")
    print(f'  Query: "{query}"')
    print(f"  Endpoint: POST {AGENT_BASE}/fiber-agent/stream")
    print(f"{'─' * 60}")

    start = time.time()
    event_counts: dict[str, int] = {}
    final_output = ""
    events_received: list[dict] = []

    try:
        with httpx.stream(
            "POST",
            f"{AGENT_BASE}/fiber-agent/stream",
            json={
                "input": {
                    "messages": [{"role": "user", "content": query}],
                    "thread_id": f"debug-sse-{int(time.time())}",
                    "user_input": query,
                },
                "config": {"configurable": {"thread_id": f"debug-sse-{int(time.time())}"}},
                "stream_mode": "events",
            },
            timeout=INVOKE_TIMEOUT,
        ) as resp:
            if resp.status_code != 200:
                print(f"\n  ❌ HTTP {resp.status_code}")
                return {"success": False, "error": f"HTTP {resp.status_code}"}

            print(f"  ✅ 连接成功，Content-Type: {resp.headers.get('content-type', 'N/A')}")
            print(f"{'─' * 60}")
            print("  事件流:")

            buffer = ""
            for chunk in resp.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    if not block.strip():
                        continue

                    # 解析 SSE 块
                    data_str = ""
                    for line in block.split("\n"):
                        if line.startswith("data: "):
                            data_str += line[6:]

                    if not data_str or data_str == "[DONE]":
                        continue

                    try:
                        event = json.loads(data_str)
                        event_type = event.get("event", "unknown")
                        event_name = event.get("name", "")
                        event_counts[event_type] = event_counts.get(event_type, 0) + 1

                        elapsed = round((time.time() - start) * 1000)
                        display_name = f" ({event_name})" if event_name else ""

                        # 检查 final_output 事件
                        if event_type == "final_output":
                            final_output = event.get("data", {}).get("output", "")
                            print(
                                f'  [{elapsed:>6}ms] 🎯 {event_type}: "{final_output[:60]}..."'
                                if len(final_output) > 60
                                else f'  [{elapsed:>6}ms] 🎯 {event_type}: "{final_output}"'
                            )
                        elif event_type == "heartbeat":
                            hb_ms = event.get("data", {}).get("elapsed_ms", 0)
                            print(f"  [{elapsed:>6}ms] 💓 {event_type} (elapsed={hb_ms}ms)")
                        elif event_type == "error":
                            err_msg = event.get("data", {}).get("message", "")
                            print(f"  [{elapsed:>6}ms] ❌ {event_type}: {err_msg}")
                        elif event_type in ("on_chain_start", "on_chain_end"):
                            print(f"  [{elapsed:>6}ms] {event_type}{display_name}")
                        else:
                            print(f"  [{elapsed:>6}ms] {event_type}{display_name}")

                        events_received.append(event)
                    except json.JSONDecodeError:
                        pass

        total_ms = round((time.time() - start) * 1000)

        # 统计摘要
        print(f"{'─' * 60}")
        print("  📊 事件统计:")
        for etype, count in sorted(event_counts.items()):
            print(f"     {etype}: {count}")
        print(f"\n  总耗时: {total_ms}ms")
        print(f"  总事件数: {len(events_received)}")

        if final_output:
            print("\n  ✅ 收到 final_output 事件:")
            print(f'     "{final_output}"')
            return {"success": True, "final_output": final_output, "total_ms": total_ms}
        else:
            print("\n  ⚠️  未收到 final_output 事件")
            print("     如果是快速路径查询，这可能表示后端未正确发送 final_output")
            return {"success": False, "error": "no_final_output", "total_ms": total_ms}

    except httpx.TimeoutException:
        print(f"\n  ❌ SSE 流超时 ({INVOKE_TIMEOUT}s)")
        return {"success": False, "error": "timeout"}
    except httpx.ConnectError:
        print("\n  ❌ 无法连接到 Agent (localhost:8000)")
        return {"success": False, "error": "connect_error"}
    except Exception as e:
        print(f"\n  ❌ 错误: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# Trace 文件分析
# =============================================================================


def find_latest_trace() -> Path | None:
    """查找最新的 trace 文件。"""
    traces_dir = Path(__file__).parent.parent / "data" / "traces"
    if not traces_dir.exists():
        return None
    trace_files = sorted(traces_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    return trace_files[0] if trace_files else None


def print_trace_analysis():
    """分析并打印最新的 trace 文件。"""
    trace_file = find_latest_trace()
    if not trace_file:
        print("\n  ℹ️  未找到 trace 文件 (data/traces/*.json)")
        return

    print(f"\n{'=' * 60}")
    print(f"  📊 Trace 分析: {trace_file.name}")
    print(f"{'=' * 60}")

    try:
        with open(trace_file, "r", encoding="utf-8") as f:
            trace = json.load(f)

        print(f"  Trace ID: {trace.get('trace_id', 'N/A')}")
        print(f"  Input: \"{trace.get('user_input', 'N/A')}\"")
        print(f"  Path: {trace.get('processing_path', 'N/A')}")
        print(f"  Total: {trace.get('total_ms', 'N/A')}ms")
        print(f"  Status: {trace.get('status', 'N/A')}")
        print(f"  Spans: {trace.get('span_count', 0)}")

        spans = trace.get("spans", [])
        if spans:
            print(f"\n  {'─' * 52}")
            print(f"  {'Node':<20} {'Status':<8} {'Duration':<12} {'Output'}")
            print(f"  {'─' * 52}")
            for span in spans:
                node = span.get("node_name", "?")
                status = "ERROR" if span.get("error") else "OK"
                duration = f"{span.get('duration_ms', 0):.1f}ms"
                output = (span.get("output_summary") or "")[:40]
                error = (span.get("error") or "")[:40]
                display = error if error else output
                print(f"  {node:<20} {status:<8} {duration:<12} {display}")
            print(f"  {'─' * 52}")

    except Exception as e:
        print(f"  ❌ 解析 trace 文件失败: {e}")


# =============================================================================
# 主程序
# =============================================================================


def main():
    global AGENT_BASE, CPP_BACKEND_BASE

    parser = argparse.ArgumentParser(
        description="端到端调试脚本 — 发送测试请求并打印完整执行链路",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/debug_trace.py "查询光纤 3 的跨段衰耗"
  python scripts/debug_trace.py --check
  python scripts/debug_trace.py --trace
  python scripts/debug_trace.py --sse "查询光纤 3 的跨段衰耗"  # SSE 流测试
  python scripts/debug_trace.py --query "查看红色光纤" --skip-preflight
        """,
    )
    parser.add_argument("query", nargs="?", default=DEFAULT_QUERY, help="测试查询文本")
    parser.add_argument("--check", action="store_true", help="仅执行环境预检")
    parser.add_argument("--trace", action="store_true", help="分析最新 trace 文件")
    parser.add_argument("--sse", action="store_true", help="测试 SSE 流端点（验证 final_output 事件）")
    parser.add_argument("--skip-preflight", action="store_true", help="跳过预检直接发请求")
    parser.add_argument("--agent-url", default=AGENT_BASE, help=f"Agent URL (default: {AGENT_BASE})")
    parser.add_argument(
        "--backend-url", default=CPP_BACKEND_BASE, help=f"C++ Backend URL (default: {CPP_BACKEND_BASE})"
    )

    args = parser.parse_args()

    # 允许覆盖 URL
    AGENT_BASE = args.agent_url
    CPP_BACKEND_BASE = args.backend_url

    print("\n" + "╔" + "═" * 58 + "╗")
    print("║   Fiber Maintenance Agent — End-to-End Debug Trace      ║")
    print("╚" + "═" * 58 + "╝")

    # 仅分析 trace
    if args.trace:
        print_trace_analysis()
        return

    # 仅预检
    if args.check:
        run_preflight()
        return

    # SSE 流测试模式
    if args.sse:
        if not args.skip_preflight:
            run_preflight()
            print()
        result = sse_test(args.query)
        print(f"\n{'=' * 60}")
        if result.get("success"):
            print(f"  ✅ SSE 测试通过 | 耗时={result.get('total_ms', '?')}ms")
        else:
            print(f"  ❌ SSE 测试失败 | Error={result.get('error', 'unknown')}")
        print(f"{'=' * 60}\n")
        sys.exit(0 if result.get("success") else 1)

    # 预检 + 请求
    if not args.skip_preflight:
        all_ok = run_preflight()
        if not all_ok:
            print("\n  继续发送请求（可能失败）...\n")

    result = invoke_test(args.query)

    # 请求后分析 trace
    if result.get("success"):
        print_trace_analysis()

    # 最终总结
    print(f"\n{'=' * 60}")
    if result.get("success"):
        path = result["data"].get("processing_path", "?")
        latency = result["data"].get("latency_ms", "?")
        print(f"  ✅ 测试通过 | Path={path} | Latency={latency}ms")
    else:
        print(f"  ❌ 测试失败 | Error={result.get('error', 'unknown')}")
    print(f"{'=' * 60}\n")

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
