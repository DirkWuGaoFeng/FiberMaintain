"""
规则引擎单元测试 [v7.1]。

测试：
- 规则匹配准确率（25 条规则）
- 参数提取
- 快速路径资格
- 置信度评分
"""

from src.nodes.rule_engine import RuleEngine


class TestRuleEngine:
    """测试 L0 规则引擎。"""

    def test_single_fiber_spanloss_query(self):
        """R001: 查询光纤衰耗"""
        result = RuleEngine.match("查询光纤1的衰耗")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.fast_path_eligible is True
        assert result.confidence >= 0.9
        assert result.params.get("fiber_id") == 1

    def test_spanloss_with_kuaduan_modifier(self):
        """R001: '跨段衰耗' 修饰词匹配"""
        result = RuleEngine.match("查询光纤 3 的跨段衰耗")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.params.get("fiber_id") == 3
        assert result.fast_path_eligible is True

    def test_spanloss_with_space_in_id(self):
        """R001: 光纤 ID 前后有空格"""
        result = RuleEngine.match("查一下光纤 12 的损耗")
        assert result is not None
        assert result.intent == "spanloss_query"
        assert result.params.get("fiber_id") == 12

    def test_single_fiber_connection_query(self):
        """R002: 查询光纤连纤"""
        result = RuleEngine.match("查询光纤3的连纤")
        assert result is not None
        assert result.intent == "connection_query"
        assert result.params.get("fiber_id") == 3

    def test_fiber_performance_query(self):
        """R003: 查询光纤性能"""
        result = RuleEngine.match("查看光纤5的性能")
        assert result is not None
        assert result.intent == "performance_query"
        assert result.params.get("fiber_id") == 5

    def test_port_alarm_query(self):
        """R010: 端口告警查询"""
        result = RuleEngine.match("2号盘3号口的告警")
        assert result is not None
        assert result.intent == "port_alarm_query"
        assert result.params.get("board_id") == 2
        assert result.params.get("port_id") == 3

    def test_color_query_red(self):
        """R020: 红色光纤查询"""
        result = RuleEngine.match("有哪些红色光纤")
        assert result is not None
        assert result.intent == "colored_query"
        assert result.params.get("color") == "RED"

    def test_stats_query_total(self):
        """R030: 光纤总数统计"""
        result = RuleEngine.match("光纤总数有多少")
        assert result is not None
        assert result.intent == "stats_query"

    def test_knowledge_qa(self):
        """R040: 知识问答"""
        result = RuleEngine.match("什么是OTDR")
        assert result is not None
        assert result.intent == "knowledge_qa"
        assert result.fast_path_eligible is False

    def test_report_generation(self):
        """R060: 报告生成"""
        result = RuleEngine.match("生成本周报告")
        assert result is not None
        assert result.intent == "report_generation"
        assert result.fast_path_eligible is False

    def test_batch_query_all_red(self):
        """R070: 批量查询红色光纤"""
        result = RuleEngine.match("所有红色光纤")
        assert result is not None
        assert result.intent == "batch_query"
        assert result.fast_path_eligible is False

    def test_no_match_returns_none(self):
        """无法识别的输入返回 None。"""
        result = RuleEngine.match("今天天气怎么样")
        assert result is None

    def test_fib_format_extraction(self):
        """测试 FIB-XXXX 格式提取。"""
        result = RuleEngine.match("查询FIB-0012的衰耗")
        assert result is not None
        assert result.params.get("fiber_id") == 12

    def test_fast_path_simple_query(self):
        """简单的单纤查询具备快速路径资格。"""
        result = RuleEngine.match("查光纤1的衰耗")
        assert result is not None
        assert result.fast_path_eligible is True

    def test_complex_query_not_fast_path(self):
        """分析/诊断查询不具备 fast_path 资格。"""
        result = RuleEngine.match("分析光纤3")
        assert result is not None
        assert result.intent == "spanloss_analysis"
        assert result.fast_path_eligible is False

    def test_color_diagnosis_not_fast_path(self):
        """颜色诊断需要多步分析。"""
        result = RuleEngine.match("光纤1为什么变红")
        assert result is not None
        assert result.intent == "color_diagnosis"
        assert result.fast_path_eligible is False


class TestRuleEngineEdgeCases:
    """边界情况测试。"""

    def test_empty_input(self):
        result = RuleEngine.match("")
        assert result is None

    def test_very_long_input(self):
        """长输入仍应正常工作（内部会截断）。"""
        long_input = "查询光纤1的衰耗" + "x" * 2000
        result = RuleEngine.match(long_input)
        # 应匹配开头处的 spanloss 模式
        assert result is not None

    def test_special_characters(self):
        """特殊字符不应导致崩溃。"""
        result = RuleEngine.match("查询光纤@#$%的衰耗")
        # 不应抛出异常，可以匹配也可以不匹配
        assert True

    def test_health_check(self):
        """R080: 系统健康检查。"""
        result = RuleEngine.match("系统健康检查")
        assert result is not None
        assert result.intent == "health_check"
