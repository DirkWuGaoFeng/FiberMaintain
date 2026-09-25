"""
测试：P2 锦上添花改进（CodeOrchestrator, MemoryEval）。
"""

import time

from src.memory.memory_eval import (
    MemoryEntry,
    MemoryEvalFramework,
    MemoryEvalReport,
    quick_eval,
)
from src.tools.code_orchestrator import (
    CodeOrchestrator,
    CodePlan,
    CodeStep,
    run_code_plan,
)


# ═══════════════════════════════════════════════════════════════════
# CodeOrchestrator 测试
# ═══════════════════════════════════════════════════════════════════
class TestCodeOrchestrator:
    def test_plan_from_goal_statistics(self):
        orchestrator = CodeOrchestrator()
        plan = orchestrator.plan_from_goal("计算光纤衰耗的统计分布")
        assert len(plan.steps) >= 1
        assert "统计" in plan.steps[0].description or "统计" in plan.goal

    def test_plan_from_goal_filter(self):
        orchestrator = CodeOrchestrator()
        plan = orchestrator.plan_from_goal("筛选红色光纤")
        assert len(plan.steps) >= 1

    def test_validate_safe_code(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="统计",
            steps=[CodeStep(description="统计", code="data = context.get('data', [])\nresult = {'count': len(data)}")],
        )
        result = orchestrator.validate_plan(plan)
        assert result.safe is True

    def test_validate_detects_exec(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="危险",
            steps=[CodeStep(description="危险", code="exec('import os')")],
        )
        result = orchestrator.validate_plan(plan)
        assert result.safe is False
        assert any("exec" in v for v in result.violations)

    def test_validate_detects_eval(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="危险",
            steps=[CodeStep(description="危险", code="eval('1+1')")],
        )
        result = orchestrator.validate_plan(plan)
        assert result.safe is False

    def test_validate_detects_import_os(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="危险",
            steps=[CodeStep(description="危险", code="import os")],
        )
        result = orchestrator.validate_plan(plan)
        assert result.safe is False

    def test_validate_detects_while_true(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="危险",
            steps=[CodeStep(description="危险", code="while True:\n    pass")],
        )
        result = orchestrator.validate_plan(plan)
        assert result.safe is False

    def test_validate_detects_file_write(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="危险",
            steps=[CodeStep(description="危险", code="open('file.txt', 'w').write('test')")],
        )
        result = orchestrator.validate_plan(plan)
        assert result.safe is False

    def test_execute_statistics_plan(self):
        orchestrator = CodeOrchestrator()
        plan = orchestrator.plan_from_goal("计算光纤衰耗的统计分布")
        data = {
            "data": [
                {"value": 0.5, "fiber_id": 1},
                {"value": 1.2, "fiber_id": 2},
                {"value": 0.8, "fiber_id": 3},
            ]
        }
        result = orchestrator.execute_plan(plan, context=data)
        assert result.success is True
        assert "count" in result.output or "3" in result.output

    def test_execute_with_invalid_code(self):
        orchestrator = CodeOrchestrator()
        plan = CodePlan(
            goal="测试",
            steps=[CodeStep(description="错误代码", code="raise ValueError('test error')")],
        )
        result = orchestrator.execute_plan(plan)
        assert result.success is False
        assert "test error" in result.error

    def test_run_code_plan_convenience(self):
        result = run_code_plan("计算统计", data={"data": [{"value": 10}, {"value": 20}, {"value": 30}]})
        assert result.success is True

    def test_complexity_score(self):
        orchestrator = CodeOrchestrator()
        simple_plan = CodePlan(
            goal="简单",
            steps=[CodeStep(description="简单", code="x = 1")],
        )
        complex_plan = CodePlan(
            goal="复杂",
            steps=[
                CodeStep(
                    description="复杂",
                    code=(
                        "for i in range(10):\n"
                        "    if i > 5:\n"
                        "        while i < 8:\n"
                        "            pass\n"
                        "    try:\n"
                        "        pass\n"
                        "    except:\n"
                        "        pass"
                    ),
                )
            ],
        )
        simple_result = orchestrator.validate_plan(simple_plan)
        complex_result = orchestrator.validate_plan(complex_plan)
        assert complex_result.complexity_score > simple_result.complexity_score


# ═══════════════════════════════════════════════════════════════════
# MemoryEvalFramework 测试
# ═══════════════════════════════════════════════════════════════════
class TestMemoryEvalFramework:
    def test_evaluate_empty(self):
        evaluator = MemoryEvalFramework()
        report = evaluator.evaluate([])
        assert report.entry_count == 0
        assert report.overall_score == 0.0
        assert len(report.recommendations) > 0

    def test_evaluate_single_entry(self):
        evaluator = MemoryEvalFramework()
        entries = [
            MemoryEntry(
                id="1",
                content="用户偏好 JSON 格式输出",
                category="preference",
                created_at=time.time() - 3600,
                updated_at=time.time() - 3600,
                confidence=1.0,
                source="user",
            )
        ]
        report = evaluator.evaluate(entries, context="用户偏好")
        assert report.entry_count == 1
        assert report.overall_score >= 0

    def test_evaluate_relevance(self):
        evaluator = MemoryEvalFramework()
        entries = [
            MemoryEntry(
                id="1",
                content="用户偏好 JSON 格式",
                category="preference",
                created_at=time.time(),
                updated_at=time.time(),
            )
        ]
        # 相关上下文
        report = evaluator.evaluate(entries, context="用户偏好设置")
        relevant_score = 0
        for s in report.scores:
            if s.dimension == "relevance":
                relevant_score = s.score

        # 不相关上下文
        report2 = evaluator.evaluate(entries, context="查询光纤告警")
        irrelevant_score = 0
        for s in report2.scores:
            if s.dimension == "relevance":
                irrelevant_score = s.score

        assert relevant_score > irrelevant_score

    def test_evaluate_freshness(self):
        evaluator = MemoryEvalFramework()
        # 新鲜记忆
        fresh_entry = MemoryEntry(
            id="1",
            content="fresh",
            category="fact",
            created_at=time.time(),
            updated_at=time.time(),
        )
        fresh_report = evaluator.evaluate([fresh_entry])
        fresh_score = 0
        for s in fresh_report.scores:
            if s.dimension == "freshness":
                fresh_score = s.score

        # 过时记忆 (365天前)
        old_entry = MemoryEntry(
            id="2",
            content="old",
            category="fact",
            created_at=time.time() - 86400 * 365,
            updated_at=time.time() - 86400 * 365,
        )
        old_report = evaluator.evaluate([old_entry])
        old_score = 0
        for s in old_report.scores:
            if s.dimension == "freshness":
                old_score = s.score

        assert fresh_score > old_score

    def test_evaluate_coverage(self):
        evaluator = MemoryEvalFramework()
        # 单一类别
        single = [
            MemoryEntry(
                id="1",
                content="test",
                category="preference",
                created_at=time.time(),
                updated_at=time.time(),
            )
        ]
        single_report = evaluator.evaluate(single)
        single_score = 0
        for s in single_report.scores:
            if s.dimension == "coverage":
                single_score = s.score

        # 多类别
        multi = [
            MemoryEntry(id="1", content="p1", category="preference", created_at=time.time(), updated_at=time.time()),
            MemoryEntry(id="2", content="h1", category="history", created_at=time.time(), updated_at=time.time()),
            MemoryEntry(id="3", content="f1", category="fact", created_at=time.time(), updated_at=time.time()),
            MemoryEntry(id="4", content="pat1", category="pattern", created_at=time.time(), updated_at=time.time()),
        ]
        multi_report = evaluator.evaluate(multi)
        multi_score = 0
        for s in multi_report.scores:
            if s.dimension == "coverage":
                multi_score = s.score

        assert multi_score > single_score

    def test_evaluate_redundancy(self):
        evaluator = MemoryEvalFramework()
        # 无重复
        unique = [
            MemoryEntry(
                id="1", content="unique content 1", category="fact", created_at=time.time(), updated_at=time.time()
            ),
            MemoryEntry(
                id="2", content="unique content 2", category="fact", created_at=time.time(), updated_at=time.time()
            ),
        ]
        unique_report = evaluator.evaluate(unique)
        unique_score = 0
        for s in unique_report.scores:
            if s.dimension == "redundancy":
                unique_score = s.score

        # 有重复
        dup = [
            MemoryEntry(
                id="1",
                content="duplicate content here",
                category="fact",
                created_at=time.time(),
                updated_at=time.time(),
            ),
            MemoryEntry(
                id="2",
                content="duplicate content here",
                category="fact",
                created_at=time.time(),
                updated_at=time.time(),
            ),
        ]
        dup_report = evaluator.evaluate(dup)
        dup_score = 0
        for s in dup_report.scores:
            if s.dimension == "redundancy":
                dup_score = s.score

        assert unique_score > dup_score

    def test_quick_eval_convenience(self):
        entries = [
            {
                "id": "1",
                "content": "偏好 JSON",
                "category": "preference",
                "created_at": time.time(),
                "updated_at": time.time(),
            },
        ]
        report = quick_eval(entries, context="偏好")
        assert report.entry_count == 1
        assert isinstance(report, MemoryEvalReport)

    def test_recommendations_for_empty(self):
        evaluator = MemoryEvalFramework()
        report = evaluator.evaluate([])
        assert len(report.recommendations) > 0
        assert any("空" in r for r in report.recommendations)
