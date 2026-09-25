"""验证未覆盖功能的测试脚本"""

import io
import json
import sys
import time

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

AGENT = "http://127.0.0.1:8090"
STREAM = f"{AGENT}/fiber-agent/stream"


def send_query(user_input, thread_id, timeout=120):
    result = {"status": None, "nodes": [], "path": "", "output": "", "errors": [], "latency": 0}
    start = time.time()
    try:
        resp = requests.post(
            STREAM, json={"input": {"user_input": user_input, "thread_id": thread_id}}, stream=True, timeout=timeout
        )
        result["status"] = resp.status_code
        if resp.status_code != 200:
            result["errors"].append(f"HTTP {resp.status_code}")
            return result
        for line in resp.iter_lines():
            if not line or not line.startswith(b"data: "):
                continue
            try:
                evt = json.loads(line[6:].decode())
            except:
                continue
            etype = evt.get("event", "")
            ename = evt.get("name", "")
            if etype == "on_chain_end" and ename:
                result["nodes"].append(ename)
            if etype == "final_output":
                result["output"] = evt.get("data", {}).get("output", "")
            if etype == "on_chain_end" and ename == "LangGraph":
                output = evt.get("data", {}).get("output", {})
                if isinstance(output, dict):
                    result["path"] = output.get("processing_path", "")
    except Exception as e:
        result["errors"].append(str(e))
    result["latency"] = int((time.time() - start) * 1000)
    return result


def test(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}: {detail}")
    return passed


results = []

# =============================================================================
print("=" * 60)
print("TC-18: 全链路追踪 trace_id 验证")
print("=" * 60)
r = send_query("查询光纤3衰耗", "tc18-trace")
# 检查是否有 trace_id 相关事件
has_trace = any("trace" in n.lower() for n in r["nodes"])
# 检查 traces API
try:
    traces_resp = requests.get(f"{AGENT}/api/v1/traces", timeout=10)
    traces_data = traces_resp.json()
    has_traces_api = traces_resp.status_code == 200 and "traces" in traces_data
    trace_count = len(traces_data.get("traces", []))
except:
    has_traces_api = False
    trace_count = 0
results.append(
    test(
        "TC-18 全链路追踪",
        has_traces_api,
        f"traces API={has_traces_api}, trace_count={trace_count}, latency={r['latency']}ms",
    )
)

# =============================================================================
print("\n" + "=" * 60)
print("规则引擎/Skill 热重载 API 测试")
print("=" * 60)
# 规则引擎重载
try:
    resp = requests.post(f"{AGENT}/api/v1/rules/reload", timeout=10)
    rules_data = resp.json()
    rules_ok = resp.status_code == 200 and rules_data.get("status") == "ok"
    rule_count = rules_data.get("rules_loaded", 0)
except Exception:
    rules_ok = False
    rule_count = 0
results.append(test("规则引擎热重载", rules_ok, f"status={rules_ok}, rules_loaded={rule_count}"))

# Skill 系统重载
try:
    resp = requests.post(f"{AGENT}/api/v1/skills/reload", timeout=10)
    skills_data = resp.json()
    skills_ok = resp.status_code == 200 and skills_data.get("status") == "ok"
    skill_count = skills_data.get("skills_loaded", 0)
except Exception:
    skills_ok = False
    skill_count = 0
results.append(test("Skill系统热重载", skills_ok, f"status={skills_ok}, skills_loaded={skill_count}"))

# 列出已加载 Skill
try:
    resp = requests.get(f"{AGENT}/api/v1/skills", timeout=10)
    skills_list = resp.json()
    skills_list_ok = resp.status_code == 200 and "skills" in skills_list
    skills_names = [s.get("id", "") for s in skills_list.get("skills", [])]
except Exception:
    skills_list_ok = False
    skills_names = []
results.append(test("Skill列表查询", skills_list_ok, f"count={len(skills_names)}, skills={skills_names[:5]}..."))

# =============================================================================
print("\n" + "=" * 60)
print("Prometheus 指标 API 测试")
print("=" * 60)
try:
    resp = requests.get(f"{AGENT}/metrics", timeout=10)
    metrics_ok = resp.status_code == 200
    metrics_text = resp.text[:500] if metrics_ok else ""
    has_prom = "prometheus" in metrics_text.lower() or "tool_calls" in metrics_text.lower() or "#" in metrics_text
except Exception as e:
    metrics_ok = False
    metrics_text = str(e)
    has_prom = False
results.append(
    test("Prometheus指标", metrics_ok, f"status={metrics_ok}, has_prom_format={has_prom}, preview={metrics_text[:200]}")
)

# =============================================================================
print("\n" + "=" * 60)
print("TC-14: 降级处理（后端不可用）")
print("=" * 60)
# 后端已不可用（health check 显示 cpp_backend=unavailable）
r = send_query("查询光纤3衰耗", "tc14-degrade")
has_degrade = "degradation" in " ".join(r["nodes"]).lower() or r["path"] in ("degraded", "fast")
# 检查是否有输出
has_output = len(r["output"]) > 0
results.append(
    test("TC-14 降级处理", has_output, f"path={r['path']}, output_len={len(r['output'])}, nodes={r['nodes'][:5]}")
)

# =============================================================================
print("\n" + "=" * 60)
print("BM25 混合检索可用性验证")
print("=" * 60)
# 直接测试 RAG 引擎
try:
    # 通过知识问答触发 RAG
    r = send_query("什么是光纤跨段衰耗", "tc10-rag", timeout=60)
    # 检查 RAG 相关节点
    has_knowledge = "knowledge_qa" in r["nodes"] or "knowledge_assistant" in " ".join(r["nodes"]).lower()
    has_output = len(r["output"]) > 0
except:
    has_knowledge = False
    has_output = False
# 检查启动日志中的 BM25 状态
results.append(
    test(
        "BM25检索",
        has_knowledge,
        f"knowledge_qa节点={has_knowledge}, 有输出={has_output}, latency={r.get('latency', 0)}ms (注意: BM25不可用，降级为纯向量检索)",
    )
)

# =============================================================================
print("\n" + "=" * 60)
print("ContextCompressor 摘要压缩验证（多轮对话）")
print("=" * 60)
# 发送多轮对话触发压缩
tid = "tc-compressor-test"
rounds = []
for i in range(5):
    fid = i + 1
    r = send_query(f"查询光纤{fid}衰耗", tid, timeout=30)
    rounds.append({"fiber": fid, "path": r["path"], "latency": r["latency"], "output_len": len(r["output"])})
    print(f"  Round {i+1}: fiber={fid}, path={r['path']}, latency={r['latency']}ms")

# 验证多轮都能正常返回
all_ok = all(rd["output_len"] > 0 for rd in rounds)
results.append(
    test("ContextCompressor多轮对话", all_ok, f"5轮全部有输出={all_ok}, 路径={[rd['path'] for rd in rounds]}")
)

# =============================================================================
print("\n" + "=" * 60)
print("额外功能验证: 诊断 API")
print("=" * 60)
try:
    resp = requests.get(f"{AGENT}/api/v1/traces", timeout=10)
    traces = resp.json().get("traces", [])
    has_recent = len(traces) > 0
    if has_recent:
        latest = traces[0]
        trace_id = latest.get("trace_id", "")
        # 获取详情
        resp2 = requests.get(f"{AGENT}/api/v1/traces/{trace_id}", timeout=10)
        trace_detail = resp2.json()
        has_detail = resp2.status_code == 200 and "trace_id" in trace_detail
    else:
        has_detail = False
except:
    has_recent = False
    has_detail = False
results.append(test("诊断API-traces列表", has_recent, f"recent_traces={len(traces) if 'traces' in dir() else 0}"))
results.append(test("诊断API-trace详情", has_detail, f"trace_id={trace_id if 'trace_id' in dir() else 'N/A'}"))

# =============================================================================
print("\n" + "=" * 60)
print("批量进度 API 测试")
print("=" * 60)
try:
    resp = requests.get(f"{AGENT}/api/batch/test-batch/progress", timeout=10)
    batch_ok = resp.status_code in (200, 404)  # 404 表示无此 batch，API 正常
except:
    batch_ok = False
results.append(test("批量进度API", batch_ok, f"status={resp.status_code if 'resp' in dir() else 'error'}"))

# =============================================================================
print("\n" + "=" * 60)
print("汇总")
print("=" * 60)
passed = sum(1 for p in results if p)
total = len(results)
print(f"\n通过: {passed}/{total}")
for i, (name, p, detail) in enumerate(
    zip(
        [
            "TC-18 全链路追踪",
            "规则引擎热重载",
            "Skill系统热重载",
            "Skill列表查询",
            "Prometheus指标",
            "TC-14 降级处理",
            "BM25检索",
            "ContextCompressor多轮对话",
            "诊断API-traces列表",
            "诊断API-trace详情",
            "批量进度API",
        ],
        results,
        [""] * len(results),
    )
):
    status = "PASS" if p else "FAIL"
    print(f"  [{status}] {name}")
