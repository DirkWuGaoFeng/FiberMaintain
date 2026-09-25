#!/usr/bin/env python
"""
Bad Case 挖掘脚本 —— 生产轨迹回流评估资产（书籍 Ch6：可观测性回流）。

【功能】
扫描 data/traces/*.json，按规则筛出可疑轨迹，输出候选清单。
候选经人工标注后，按 tests/eval/e2e_dataset.json 格式追加为新用例。

【筛选规则】
1. status != SUCCESS
2. processing_path 异常（degraded / blocked 且非注入类输入）
3. spans 中存在 error
4. 总耗时异常（> SLOW_THRESHOLD_MS）
5. final_output 为空但 status=SUCCESS（静默失败）

用法:
    python scripts/harvest_badcases.py [--out data/eval/badcase_candidates.md]

输出:
    - Markdown 候选清单（供人工标注）
    - JSON 原始候选（供脚本处理）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TRACES_DIR = PROJECT_ROOT / "data" / "traces"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "eval"

# 总耗时异常阈值（毫秒）
SLOW_THRESHOLD_MS = 60_000

# 注入类关键词（blocked 路径对注入输入是正确行为，不算 bad case）
_INJECTION_MARKERS = ("忽略之前", "ignore previous", "系统提示词", "开发者模式", "SYSTEM:")


def _is_injection_input(user_input: str) -> bool:
    lowered = user_input.lower()
    return any(m.lower() in lowered for m in _INJECTION_MARKERS)


def classify(trace: dict) -> list[str]:
    """返回该轨迹命中的可疑原因列表（空 = 正常）。"""
    reasons: list[str] = []
    user_input = trace.get("user_input", "")

    if trace.get("status") != "SUCCESS":
        reasons.append(f"status={trace.get('status')}")

    path = trace.get("processing_path", "")
    if path == "blocked" and not _is_injection_input(user_input):
        reasons.append("误拦截（blocked 但非注入输入）")
    elif path == "degraded":
        reasons.append("降级路径")

    for span in trace.get("spans") or []:
        if span.get("error"):
            reasons.append(f"span error @ {span.get('node_name', '?')}: {str(span['error'])[:60]}")
            break

    if trace.get("total_ms", 0) > SLOW_THRESHOLD_MS:
        reasons.append(f"耗时异常 ({trace['total_ms']:.0f}ms)")

    if trace.get("status") == "SUCCESS" and not trace.get("final_output"):
        reasons.append("静默失败（SUCCESS 但无输出）")

    return reasons


def harvest() -> list[dict]:
    """扫描全部轨迹，返回候选清单。"""
    candidates = []
    if not TRACES_DIR.exists():
        print(f"轨迹目录不存在: {TRACES_DIR}")
        return []

    for fp in sorted(TRACES_DIR.glob("*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                trace = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        reasons = classify(trace)
        if reasons:
            candidates.append(
                {
                    "trace_id": trace.get("trace_id", fp.stem),
                    "user_input": trace.get("user_input", "")[:120],
                    "processing_path": trace.get("processing_path", ""),
                    "status": trace.get("status", ""),
                    "timestamp": trace.get("timestamp", ""),
                    "reasons": reasons,
                }
            )
    return candidates


def write_reports(candidates: list[dict], out_dir: Path) -> None:
    """输出 Markdown 候选清单 + JSON。"""
    out_dir.mkdir(parents=True, exist_ok=True)

    md_lines = [
        "# Bad Case 候选清单（待人工标注）",
        "",
        f"共 {len(candidates)} 条候选。标注方式：确认后按 "
        "`tests/eval/e2e_dataset.json` 格式追加用例（含 expected_intent / "
        "expected_tools / expected_params），并在 id 中沿用 trace_id。",
        "",
        "| trace_id | 时间 | 路径 | 原因 | 用户输入 |",
        "|---|---|---|---|---|",
    ]
    for c in candidates:
        reasons = "; ".join(c["reasons"]).replace("|", "/")
        user_input = c["user_input"].replace("|", "/") or "(空)"
        md_lines.append(
            f"| {c['trace_id']} | {c['timestamp'][:10]} | {c['processing_path']} " f"| {reasons} | {user_input} |"
        )

    (out_dir / "badcase_candidates.md").write_text("\n".join(md_lines), encoding="utf-8")
    with open(out_dir / "badcase_candidates.json", "w", encoding="utf-8") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    print(f"候选清单已输出: {out_dir / 'badcase_candidates.md'}")
    print(f"原始候选 JSON: {out_dir / 'badcase_candidates.json'}")


def main():
    parser = argparse.ArgumentParser(description="从生产轨迹挖掘 bad case 候选")
    parser.add_argument("--out", default=str(DEFAULT_OUT_DIR), help="输出目录")
    args = parser.parse_args()

    candidates = harvest()
    print(f"扫描完成: {len(candidates)} 条候选")
    write_reports(candidates, Path(args.out))

    # 无候选也视为成功（退出码 0）；保留 1 给目录缺失等异常
    sys.exit(0)


if __name__ == "__main__":
    main()
