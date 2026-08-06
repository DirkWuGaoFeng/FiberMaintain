"""
Functional regression tests [v7.2].

Ensures v7.2 changes (new rules, tracer, timeout config) don't break existing functionality:
- Original rules R001-R080 match correctly
- Routing logic unaffected by new rules
- Fast path templates render correctly
- Observability module exports complete
"""

import pytest

from src.nodes.rule_engine import RuleEngine


class TestExistingRulesUnchanged:
    """Verify R001-R080 original rules still work after v7.2 additions."""

    @pytest.mark.parametrize("query,expected_intent,expected_params", [
        # R001: spanloss query
        ("查询光纤1的衰耗", "spanloss_query", {"fiber_id": 1}),
        ("查询光纤 3 的跨段衰耗", "spanloss_query", {"fiber_id": 3}),
        ("查一下光纤 12 的损耗", "spanloss_query", {"fiber_id": 12}),
        # R002: connection query
        ("查询光纤3的连纤", "connection_query", {"fiber_id": 3}),
        # R003: performance query
        ("查看光纤5的性能", "performance_query", {"fiber_id": 5}),
        # R010: port alarm
        ("2号盘3号口的告警", "port_alarm_query", {"board_id": 2, "port_id": 3}),
        # R020: colored query
        ("有哪些红色光纤", "colored_query", {"color": "RED"}),
        ("查看黄色光纤", "colored_query", {"color": "YELLOW"}),
        # R030: stats
        ("光纤总数有多少", "stats_query", {}),
        # R040: knowledge QA
        ("什么是OTDR", "knowledge_qa", {}),
        # R060: report
        ("生成本周报告", "report_generation", {}),
        # R070: batch
        ("所有红色光纤", "batch_query", {}),
        # R080: health check
        ("系统健康检查", "health_check", {}),
    ])
    def test_existing_rule_match(self, query, expected_intent, expected_params):
        """Original rules produce correct intent and params."""
        result = RuleEngine.match(query)
        assert result is not None, f"No match for: {query}"
        assert result.intent == expected_intent, (
            f"'{query}': expected intent={expected_intent}, got={result.intent}"
        )
        for key, value in expected_params.items():
            assert result.params.get(key) == value, (
                f"'{query}': expected {key}={value}, got={result.params.get(key)}"
            )

    def test_fib_format_still_works(self):
        """FIB-XXXX format extraction unchanged."""
        result = RuleEngine.match("查询FIB-0012的衰耗")
        assert result is not None
        assert result.params.get("fiber_id") == 12

    def test_no_match_still_returns_none(self):
        """Unrecognized input still returns None."""
        assert RuleEngine.match("今天天气怎么样") is None
        assert RuleEngine.match("") is None
        assert RuleEngine.match("hello world") is None

    def test_fast_path_eligibility_unchanged(self):
        """Fast path flags unchanged for original rules."""
        # Simple queries → fast_path=True
        assert RuleEngine.match("查光纤1的衰耗").fast_path_eligible is True
        assert RuleEngine.match("查看光纤5的性能").fast_path_eligible is True

        # Complex queries → fast_path=False
        assert RuleEngine.match("分析光纤3").fast_path_eligible is False
        assert RuleEngine.match("什么是OTDR").fast_path_eligible is False
        assert RuleEngine.match("生成本周报告").fast_path_eligible is False


class TestRoutingUnchanged:
    """Routing logic not affected by new rules."""

    def test_route_after_rule_engine_fast_path(self):
        """Fast path routing still works."""
        from src.graph.routing import route_after_rule_engine
        state = {"rule_match": {"fast_path_eligible": True, "confidence": 1.0}}
        assert route_after_rule_engine(state) == "fast_path"

    def test_route_after_rule_engine_complex(self):
        """Complex rule routing still works."""
        from src.graph.routing import route_after_rule_engine
        state = {"rule_match": {"fast_path_eligible": False, "confidence": 1.0}}
        assert route_after_rule_engine(state) == "rule_hit_complex"

    def test_route_after_rule_engine_miss(self):
        """Rule miss routing still works."""
        from src.graph.routing import route_after_rule_engine
        state = {"rule_match": None}
        assert route_after_rule_engine(state) == "rule_miss"

    def test_route_by_intent_all_types(self):
        """Intent routing covers all types."""
        from src.graph.routing import route_by_intent

        assert route_by_intent({"intent": "single_query"}) == "data_query"
        assert route_by_intent({"intent": "spanloss_query"}) == "data_query"
        assert route_by_intent({"intent": "connection_query"}) == "data_query"
        assert route_by_intent({"intent": "batch_query"}) == "batch_query"
        assert route_by_intent({"intent": "knowledge_qa"}) == "knowledge_qa"
        assert route_by_intent({"intent": "report_generation"}) == "report"
        assert route_by_intent({"intent": "chitchat"}) == "chitchat"

    def test_route_after_analysis_safeguards(self):
        """Four termination safeguards still active."""
        from src.graph.routing import route_after_analysis

        # Loop limit
        state = {
            "analysis_verdict": {"need_more_data": True},
            "loop_count": 3, "max_loops": 3,
            "llm_call_count": 1, "max_llm_calls": 10,
            "no_progress_count": 0,
        }
        assert route_after_analysis(state) != "need_more_data"

        # LLM budget
        state["loop_count"] = 0
        state["llm_call_count"] = 10
        assert route_after_analysis(state) != "need_more_data"


class TestFastPathTemplates:
    """All output templates render correctly."""

    def test_all_templates_exist(self):
        """TEMPLATES dict has all required template IDs."""
        from src.nodes.fast_path_executor import TEMPLATES

        required = [
            "T_SPANLOSS", "T_CONNECTION", "T_PERFORMANCE",
            "T_FIBER_ALARM", "T_FIBER_STATUS", "T_PORT_ALARM",
            "T_BOARD", "T_COLORED", "T_STATS", "T_TREND",
        ]
        for tid in required:
            assert tid in TEMPLATES, f"Missing template: {tid}"

    def test_spanloss_template_render(self):
        """T_SPANLOSS template renders with params."""
        from src.nodes.fast_path_executor import TEMPLATES
        template = TEMPLATES["T_SPANLOSS"]
        result = template.format(fiber_id=1, spanloss=3.2, threshold=5.0, status="正常")
        assert "光纤 1" in result
        assert "3.2" in result
        assert "正常" in result

    def test_connection_template_render(self):
        """T_CONNECTION template renders."""
        from src.nodes.fast_path_executor import TEMPLATES
        template = TEMPLATES["T_CONNECTION"]
        result = template.format(fiber_id=3, data="NE1-Port1 → NE2-Port2")
        assert "光纤 3" in result
        assert "NE1" in result

    def test_colored_template_render(self):
        """T_COLORED template renders."""
        from src.nodes.fast_path_executor import TEMPLATES
        template = TEMPLATES["T_COLORED"]
        result = template.format(color="RED", data="光纤1, 光纤5, 光纤8")
        assert "RED" in result


class TestObservabilityExports:
    """Observability module exports are complete."""

    def test_observability_exports(self):
        """__init__.py exports all v7.2 symbols."""
        from src.observability import (
            RequestTracer,
            TraceSpan,
            get_current_trace_id,
            get_current_tracer,
            get_recent_traces,
            metrics,
            set_current_trace_id,
            traced_node,
            write_audit_record,
        )

        # Verify they are callable/usable
        assert callable(traced_node)
        assert callable(get_current_trace_id)
        assert callable(get_current_tracer)
        assert callable(get_recent_traces)
        assert callable(set_current_trace_id)

    def test_request_tracer_importable(self):
        """RequestTracer can be imported from full path."""
        from src.observability.request_tracer import (
            SLOW_SPAN_THRESHOLD_MS,
            RequestTracer,
            TraceSpan,
            get_current_trace_id,
            get_current_tracer,
            get_recent_traces,
            set_current_trace_id,
            traced_node,
        )
        assert SLOW_SPAN_THRESHOLD_MS == 5000

    def test_config_importable(self):
        """Config module imports without error."""
        from src.config import (
            DATA_DIR,
            LLM_CONFIG,
            OLLAMA_BASE_URL,
            SPANLOSS_CRITICAL,
            SPANLOSS_THRESHOLD,
        )
        assert SPANLOSS_THRESHOLD > 0
        assert SPANLOSS_CRITICAL > SPANLOSS_THRESHOLD


class TestRuleEngineNodeIntegration:
    """rule_engine_node async function works correctly."""

    async def test_rule_engine_node_match(self):
        """Node returns correct state update on match."""
        from src.nodes.rule_engine import rule_engine_node

        state = {
            "user_input": "查询光纤1的衰耗",
            "trace_id": "reg-test-001",
            "processing_path": "normal",
        }
        result = await rule_engine_node(state)

        assert result["rule_match"] is not None
        assert result["intent"] == "spanloss_query"
        assert result["processing_path"] == "fast"

    async def test_rule_engine_node_miss(self):
        """Node returns rule_match=None on miss."""
        from src.nodes.rule_engine import rule_engine_node

        state = {
            "user_input": "帮我写一首诗",
            "trace_id": "reg-test-002",
            "processing_path": "normal",
        }
        result = await rule_engine_node(state)
        assert result["rule_match"] is None

    async def test_rule_engine_node_blocked(self):
        """Node skips when input already blocked."""
        from src.nodes.rule_engine import rule_engine_node

        state = {
            "user_input": "查询光纤1的衰耗",
            "trace_id": "reg-test-003",
            "processing_path": "blocked",
        }
        result = await rule_engine_node(state)
        assert result == {}

    async def test_rule_engine_node_v72_queries(self):
        """v7.2 colloquial queries work through the node."""
        from src.nodes.rule_engine import rule_engine_node

        # "分析连纤1中断的原因"
        state = {
            "user_input": "分析连纤1中断的原因",
            "trace_id": "reg-v72-001",
            "processing_path": "normal",
        }
        result = await rule_engine_node(state)
        assert result["intent"] == "connection_query"
        assert result["processing_path"] == "fast"

        # "目前断纤有哪些"
        state["user_input"] = "目前断纤有哪些"
        state["trace_id"] = "reg-v72-002"
        result = await rule_engine_node(state)
        assert result["intent"] == "colored_query"
        assert result["processing_path"] == "fast"
