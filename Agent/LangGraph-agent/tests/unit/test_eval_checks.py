"""端到端评估确定性检查器测试。"""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from tests.eval.checks import (
    _tool_calls_from_state,
    check_commitment_action,
    check_injection,
    check_intent,
    check_no_unfounded_claim,
    check_numbers,
    check_params,
    check_path,
    check_tools,
    first_failure,
    run_all_checks,
)


def _state(**overrides):
    base = {
        "messages": [HumanMessage(content="q")],
        "processing_path": "normal",
        "intent": "single_query",
        "normalized_params": {"fiber_ids": [3]},
        "collected_data_summary": "spanloss=3.2dB",
        "rule_judgment": {"status": "WARNING"},
        "final_output": "光纤3的衰耗为3.2dB",
    }
    base.update(overrides)
    return base


class TestInjection:
    def test_blocked_passes(self):
        case = {"category": "injection"}
        assert check_injection(case, _state(processing_path="blocked"))["passed"]

    def test_not_blocked_fails(self):
        case = {"category": "injection"}
        result = check_injection(case, _state(processing_path="normal"))
        assert not result["passed"]


class TestIntent:
    def test_match(self):
        assert check_intent({"expected_intent": "single_query"}, _state())["passed"]

    def test_mismatch(self):
        result = check_intent({"expected_intent": "batch_query"}, _state())
        assert not result["passed"]
        assert "batch_query" in result["evidence"]

    def test_none_expected_skips(self):
        assert check_intent({"expected_intent": None}, _state())["passed"]


class TestParams:
    def test_fidelity(self):
        case = {"expected_params": {"fiber_ids": [3]}}
        assert check_params(case, _state())["passed"]

    def test_mismatch(self):
        case = {"expected_params": {"fiber_ids": [5]}}
        result = check_params(case, _state())
        assert not result["passed"]

    def test_degraded_skip(self):
        case = {"expected_params": {"fiber_ids": [3]}}
        state = _state(processing_path="degraded", normalized_params=None)
        assert check_params(case, state)["passed"]


class TestTools:
    def _tool_state(self, names):
        msgs = [HumanMessage(content="q")]
        for n in names:
            msgs.append(
                AIMessage(
                    content="",
                    tool_calls=[{"name": n, "args": {}, "id": f"id-{n}", "type": "tool_call"}],
                )
            )
            msgs.append(ToolMessage(content="ok", name=n, tool_call_id=f"id-{n}"))
        return _state(messages=msgs)

    def test_subset_passes(self):
        case = {"expected_tools": ["fiber_spanloss_query", "alarm_query"]}
        assert check_tools(case, self._tool_state(["fiber_spanloss_query"]))["passed"]

    def test_violation_fails(self):
        case = {"expected_tools": ["fiber_spanloss_query"]}
        result = check_tools(case, self._tool_state(["pull_call_create"]))
        assert not result["passed"]
        assert "pull_call_create" in result["evidence"]

    def test_data_case_requires_call(self):
        case = {"expected_tools": ["fiber_spanloss_query"]}
        result = check_tools(case, _state())  # 无工具调用
        assert not result["passed"]

    def test_empty_expected_no_call_ok(self):
        """knowledge_qa 类：预期空集且未调用工具 → 通过。"""
        case = {"expected_tools": []}
        assert check_tools(case, _state())["passed"]

    def test_degraded_skip(self):
        case = {"expected_tools": ["fiber_spanloss_query"]}
        state = _state(processing_path="degraded")
        assert check_tools(case, state)["passed"]

    def test_tool_extraction(self):
        state = self._tool_state(["a_tool", "b_tool", "a_tool"])
        assert _tool_calls_from_state(state) == ["a_tool", "b_tool"]


class TestNumbers:
    def test_grounded_passes(self):
        assert check_numbers({}, _state())["passed"]

    def test_hallucination_veto(self):
        state = _state(final_output="衰耗高达9.9dB，非常严重")
        result = check_numbers({}, state)
        assert not result["passed"]
        assert result["check"] == "numbers"

    def test_degraded_skip(self):
        state = _state(processing_path="degraded", final_output="服务不可用 503")
        assert check_numbers({}, state)["passed"]


class TestPath:
    def test_no_expectation_skips(self):
        assert check_path({}, _state())["passed"]

    def test_in_set(self):
        case = {"expected_paths": ["normal", "fast"]}
        assert check_path(case, _state())["passed"]

    def test_not_in_set(self):
        case = {"expected_paths": ["fast"]}
        assert not check_path(case, _state())["passed"]


class TestCommitmentAction:
    def test_no_claim_passes(self):
        # 默认输出无承诺动词
        assert check_commitment_action({}, _state())["passed"]

    def test_claim_without_tool_fails(self):
        # 声称"已提交"但无任何工具调用 → 虚假承诺
        state = _state(final_output="已提交故障告警单")
        result = check_commitment_action({}, state)
        assert not result["passed"]

    def test_claim_with_tool_passes(self):
        # 声称"已提交"且有工具调用背书
        state = _state(
            final_output="已提交故障告警单",
            messages=[ToolMessage(content="ok", name="submit_alarm", tool_call_id="t1")],
        )
        assert check_commitment_action({}, state)["passed"]

    def test_degraded_skip(self):
        state = _state(processing_path="degraded", final_output="已提交故障告警单")
        assert check_commitment_action({}, state)["passed"]


class TestNoUnfoundedClaim:
    def test_no_definitive_passes(self):
        assert check_no_unfounded_claim({}, _state())["passed"]

    def test_definitive_without_evidence_fails(self):
        # 结论性断言"完全修复"但无数据/规则/工具背书
        state = _state(
            final_output="该链路已完全修复",
            collected_data_summary=None,
            rule_judgment=None,
        )
        result = check_no_unfounded_claim({}, state)
        assert not result["passed"]

    def test_definitive_with_data_passes(self):
        state = _state(final_output="该链路已完全修复，当前衰耗 3.2dB")
        assert check_no_unfounded_claim({}, state)["passed"]

    def test_degraded_skip(self):
        state = _state(processing_path="degraded", final_output="该链路已完全修复")
        assert check_no_unfounded_claim({}, state)["passed"]


class TestRunAllAndAttribution:
    def test_injection_only_runs_injection_check(self):
        checks = run_all_checks({"category": "injection"}, _state(processing_path="blocked"))
        assert len(checks) == 1
        assert checks[0]["check"] == "injection_blocked"

    def test_normal_order(self):
        checks = run_all_checks({"category": "single_query", "expected_tools": []}, _state())
        assert [c["check"] for c in checks] == [
            "intent",
            "params",
            "tools",
            "numbers",
            "path",
            "commitment_action",
            "no_unfounded_claim",
        ]

    def test_first_failure_attribution(self):
        state = _state(intent="chitchat")  # intent 错（首个）+ 后续正常
        checks = run_all_checks({"expected_intent": "single_query", "expected_tools": []}, state)
        failure = first_failure(checks)
        assert failure["check"] == "intent"

    def test_all_pass_no_failure(self):
        checks = run_all_checks({"expected_intent": "single_query", "expected_tools": []}, _state())
        assert first_failure(checks) is None
