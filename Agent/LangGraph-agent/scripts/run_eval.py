"""
E2E QA evaluation runner [改进清单 P0-C].

Replays the annotated dataset (tests/eval/qa_dataset.json) through the
production front-line pipeline and scores it:

  v7 mode: input_guard -> rule_engine -> [param_gate | intent_classifier -> param_gate]
  v8 mode: input_guard -> LeadRouter.resolve

Metrics (vs dataset pass_criteria):
  - intent_accuracy        : non-injection cases, intent matches label
  - injection_block_rate   : injection cases blocked by input_guard
  - param_fidelity         : expected params preserved after param_gate / router

Usage:
  python scripts/run_eval.py --mode v7
  python scripts/run_eval.py --mode v8
  python scripts/run_eval.py --mode v7 --case SQ-01
  make eval EVAL_MODE=v7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is importable when invoked via `python scripts/...`
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATASET_PATH = PROJECT_ROOT / "tests" / "eval" / "qa_dataset.json"
REPORT_PATH = PROJECT_ROOT / "data" / "eval_report.json"

# Skill-level intents (rule engine / v8 LeadRouter) mapped back to the
# v7 intent vocabulary used in expected_intent labels.
SKILL_TO_V7 = {
    "spanloss_query": "single_query",
    "fiber_status_query": "single_query",
    "fiber_alarm_query": "single_query",
    "performance_query": "single_query",
    "connection_query": "single_query",
    "port_alarm_query": "single_query",
    "board_query": "health_check",
    "colored_query": "batch_query",
    "stats_query": "batch_query",
    "batch_query": "batch_query",
    "trend_query": "trend_analysis",
    "spanloss_analysis": "spanloss_analysis",
    "color_diagnosis": "color_diagnosis",
    "health_check": "health_check",
    "report_generation": "report_generation",
    "knowledge_qa": "knowledge_qa",
}


def _intent_matches(actual: str, case: dict) -> bool:
    """Intent is correct if it equals the v7 label or an accepted skill alias."""
    expected = case["expected_intent"]
    if actual == expected:
        return True
    return SKILL_TO_V7.get(actual) == expected


def _param_fidelity(normalized: dict, expected_params: dict) -> tuple[bool, str]:
    """Check expected params survived normalization."""
    if not expected_params:
        return True, ""
    problems = []
    exp_fibers = set(expected_params.get("fiber_ids", []))
    if exp_fibers:
        got = set(normalized.get("fiber_ids") or [])
        if not exp_fibers.issubset(got):
            problems.append(f"fiber_ids expected {sorted(exp_fibers)}, got {sorted(got)}")
    exp_color = expected_params.get("color")
    if exp_color and normalized.get("color") != exp_color:
        problems.append(f"color expected {exp_color}, got {normalized.get('color')}")
    exp_boards = set(expected_params.get("board_ids", []))
    if exp_boards:
        got = set(normalized.get("board_ids") or [])
        if not exp_boards.issubset(got):
            problems.append(f"board_ids expected {sorted(exp_boards)}, got {sorted(got)}")
    exp_ne = expected_params.get("ne_id")
    if exp_ne is not None and normalized.get("ne_id") != exp_ne:
        problems.append(f"ne_id expected {exp_ne}, got {normalized.get('ne_id')}")
    return (not problems, "; ".join(problems))


async def run_case_v7(case: dict) -> dict:
    """Replay one case through the v7 front-line pipeline."""
    from src.nodes.input_guard import input_guard_node
    from src.nodes.intent_classifier import intent_classifier_node
    from src.nodes.param_gate import param_gate_node
    from src.nodes.rule_engine import rule_engine_node

    trace_id = f"eval-{case['id']}"
    state: dict = {"user_input": case["input"], "messages": [], "trace_id": trace_id}
    result = {"id": case["id"], "category": case["category"], "mode": "v7"}

    # Layer 1: input guard
    state.update(await input_guard_node(state))
    if state.get("processing_path") == "blocked":
        blocked = case["expected_intent"] == "BLOCKED"
        result.update(intent_ok=blocked, blocked=True,
                      detail="blocked by input_guard" if blocked else "wrongly blocked")
        return result
    if case["expected_intent"] == "BLOCKED":
        result.update(intent_ok=False, blocked=False, detail="injection NOT blocked")
        return result

    # Layer 0: rule engine
    state.update(await rule_engine_node(state))
    rule_match = state.get("rule_match")
    if rule_match:
        intent = rule_match["intent"]
        result["route"] = f"rule:{intent}"
    else:
        # Rule miss -> LLM classifier (real LLM call)
        try:
            state.update(await intent_classifier_node(state))
            intent = state.get("intent", "")
            result["route"] = "llm"
        except Exception as e:  # noqa: BLE001 - eval must not crash on LLM errors
            result.update(intent_ok=False, param_ok=False, detail=f"classifier error: {e}")
            return result

    result["actual_intent"] = intent
    intent_ok = _intent_matches(intent, case)
    result["intent_ok"] = intent_ok

    # Layer 2: param gate
    state.update(await param_gate_node(state))
    normalized = state.get("normalized_params") or {}
    param_ok, detail = _param_fidelity(normalized, case.get("expected_params", {}))
    result["param_ok"] = param_ok
    if not intent_ok:
        detail = f"intent expected={case['expected_intent']} actual={intent}" + (
            f"; {detail}" if detail else "")
    result["detail"] = detail
    return result


async def run_case_v8(case: dict) -> dict:
    """Replay one case through the v8 LeadRouter pipeline."""
    from src.nodes.input_guard import input_guard_node
    from src.v8.lead_router import LeadRouter

    trace_id = f"eval-{case['id']}"
    state: dict = {"user_input": case["input"], "messages": [], "trace_id": trace_id}
    result = {"id": case["id"], "category": case["category"], "mode": "v8"}

    state.update(await input_guard_node(state))
    if state.get("processing_path") == "blocked":
        blocked = case["expected_intent"] == "BLOCKED"
        result.update(intent_ok=blocked, blocked=True, param_ok=True,
                      detail="blocked by input_guard" if blocked else "wrongly blocked")
        return result
    if case["expected_intent"] == "BLOCKED":
        result.update(intent_ok=False, blocked=False, param_ok=False,
                      detail="injection NOT blocked")
        return result

    router = LeadRouter()
    try:
        plan = await router.resolve(case["input"], {}, trace_id)
    except Exception as e:  # noqa: BLE001
        result.update(intent_ok=False, param_ok=False, detail=f"router error: {e}")
        return result

    result["actual_intent"] = plan.intent
    result["route"] = f"{plan.match_type}:{plan.scenario_id}"
    expected_skill = case.get("v8_mode_skill", "")
    if expected_skill:
        intent_ok = plan.scenario_id == expected_skill or plan.intent == expected_skill
    else:
        # chitchat cases: any deterministic outcome is acceptable, must not crash
        intent_ok = True
    result["intent_ok"] = intent_ok
    result["param_ok"] = True  # v8 param normalization is out of scope here
    if not intent_ok:
        result["detail"] = (
            f"skill expected={expected_skill} actual={plan.scenario_id} ({plan.match_type})"
        )
    return result


def summarize(results: list[dict], pass_criteria: dict) -> tuple[dict, bool]:
    """Compute metrics and gate against pass_criteria."""
    injection = [r for r in results if r["id"].startswith("INJ")]
    normal = [r for r in results if not r["id"].startswith("INJ")]

    intent_ok = sum(1 for r in normal if r.get("intent_ok"))
    blocked_ok = sum(1 for r in injection if r.get("intent_ok"))
    param_cases = [r for r in normal if r.get("param_ok") is not None]
    param_ok = sum(1 for r in param_cases if r.get("param_ok"))

    metrics = {
        "total": len(results),
        "intent_accuracy": (intent_ok / len(normal)) if normal else 1.0,
        "injection_block_rate": (blocked_ok / len(injection)) if injection else 1.0,
        "param_fidelity": (param_ok / len(param_cases)) if param_cases else 1.0,
        "intent_ok": intent_ok,
        "blocked_ok": blocked_ok,
        "param_ok": param_ok,
        "normal_count": len(normal),
    }
    passed = (
        metrics["intent_accuracy"] >= pass_criteria.get("intent_accuracy", 1.0)
        and metrics["injection_block_rate"] >= pass_criteria.get("injection_block_rate", 1.0)
        and metrics["param_fidelity"] >= pass_criteria.get("param_fidelity", 0.9)
    )
    return metrics, passed


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run E2E QA evaluation [P0-C]")
    parser.add_argument("--mode", choices=["v7", "v8"], default="v7")
    parser.add_argument("--dataset", default=str(DATASET_PATH))
    parser.add_argument("--case", help="Run a single case id only")
    args = parser.parse_args()

    # Mirror production startup: load skill YAMLs into the trigger registry
    # (server.py does this via get_skill_loader at boot; without it the
    # rule engine would silently fall back to legacy inline rules).
    from src.skills.loader import get_skill_loader

    get_skill_loader()

    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    cases = dataset["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
        if not cases:
            print(f"Case '{args.case}' not found in dataset")
            return 2

    runner = run_case_v7 if args.mode == "v7" else run_case_v8
    print(f"[Eval] mode={args.mode} cases={len(cases)}")

    results = []
    for i, case in enumerate(cases, 1):
        r = await runner(case)
        results.append(r)
        status = "PASS" if r.get("intent_ok") and r.get("param_ok", True) else "FAIL"
        print(f"  [{i:>2}/{len(cases)}] {r['id']:<7} {status:<4} "
              f"route={r.get('route', 'guard')} {r.get('detail', '')}")

    metrics, passed = summarize(results, dataset.get("pass_criteria", {}))

    print("\n===== Metrics =====")
    print(f"intent_accuracy      : {metrics['intent_accuracy']:.2%} "
          f"({metrics['intent_ok']}/{metrics['normal_count']})")
    print(f"injection_block_rate : {metrics['injection_block_rate']:.2%} ({metrics['blocked_ok']})")
    print(f"param_fidelity       : {metrics['param_fidelity']:.2%} ({metrics['param_ok']})")
    print(f"gate                 : {'PASS' if passed else 'FAIL'}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {"mode": args.mode, "metrics": metrics, "passed": passed, "results": results},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[Eval] report -> {REPORT_PATH}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
