"""Prompt 回归测试脚本

对比 Prompt 修改前后的输出质量，确保修改不会引入回归。
"""

import json
import sys
from pathlib import Path

import yaml


def load_test_cases(path: str = "prompts/tests/test_cases.yaml") -> list[dict]:
    """加载测试用例"""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("test_cases", [])


def run_regression(llm, test_cases: list[dict]) -> dict:
    """
    执行回归测试

    Args:
        llm: LangChain ChatModel 实例
        test_cases: 测试用例列表

    Returns:
        测试结果摘要
    """
    from src.graph.state import IntentResult

    structured_llm = llm.with_structured_output(IntentResult)
    results = {"total": len(test_cases), "passed": 0, "failed": 0, "details": []}

    # 加载 intent classifier prompt
    prompt_path = Path("prompts/lead_agent/intent_classifier.md")
    if prompt_path.exists():
        system_prompt = prompt_path.read_text(encoding="utf-8")
    else:
        system_prompt = "You are a helpful assistant."

    from langchain_core.messages import SystemMessage, HumanMessage

    for tc in test_cases:
        name = tc["name"]
        user_input = tc["input"]
        expected = tc["expected"]

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_input),
        ]

        try:
            result: IntentResult = structured_llm.invoke(messages)

            # 验证意图
            intent_match = result.intent == expected["intent"]
            # 验证置信度
            confidence_ok = True
            if "confidence_min" in expected:
                confidence_ok = result.confidence >= expected["confidence_min"]
            if "confidence_max" in expected:
                confidence_ok = result.confidence <= expected["confidence_max"]

            passed = intent_match and confidence_ok

            detail = {
                "name": name,
                "status": "PASS" if passed else "FAIL",
                "expected_intent": expected["intent"],
                "actual_intent": result.intent,
                "confidence": result.confidence,
            }

            if passed:
                results["passed"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            detail = {
                "name": name,
                "status": "ERROR",
                "error": str(e),
            }
            results["failed"] += 1

        results["details"].append(detail)

    return results


def main():
    test_cases = load_test_cases()
    print(f"Loaded {len(test_cases)} test cases")

    try:
        from src.llm.provider import get_llm_with_fallback

        llm = get_llm_with_fallback()
    except Exception as e:
        print(f"Failed to initialize LLM: {e}")
        print("Running in dry-run mode...")
        return

    results = run_regression(llm, test_cases)

    print(f"\n{'='*60}")
    print(f"Regression Test Results: {results['passed']}/{results['total']} passed")
    print(f"{'='*60}")

    for d in results["details"]:
        status_icon = "✓" if d["status"] == "PASS" else "✗"
        print(f"  {status_icon} {d['name']}: {d['status']}")
        if d["status"] == "FAIL":
            print(f"    Expected: {d.get('expected_intent', 'N/A')}")
            print(f"    Actual:   {d.get('actual_intent', 'N/A')}")

    if results["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
