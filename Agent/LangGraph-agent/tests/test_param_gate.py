"""
ParamGate 单元测试 [v7.1]。

测试第二层参数校验：
- 格式转换（FIB-XXXX → int, N号盘 → int, N口 → int）
- 颜色映射
- 时间解析
- 批量上限校验
"""

from src.graph.state import NormalizedParams
from src.nodes.param_gate import ParamGate


class TestParamGate:
    """测试 ParamGate 参数规范化。"""

    def test_fiber_id_numeric(self):
        """抽取数字形式的光纤 ID。"""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["1"]})
        assert isinstance(result, NormalizedParams)
        assert result.fiber_ids == [1]
        assert not result.parse_failures

    def test_fiber_id_fib_format(self):
        """抽取 FIB-XXXX 格式。"""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["FIB-0001"]})
        assert 1 in result.fiber_ids

    def test_fiber_id_chinese_format(self):
        """抽取中文格式 '13号光纤'。"""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["13号光纤"]})
        assert 13 in result.fiber_ids

    def test_color_mapping_chinese(self):
        """映射中文颜色名称。"""
        result = ParamGate.validate_and_normalize({"color": "红色"})
        assert result.color == "RED"

    def test_color_mapping_english(self):
        """映射英文颜色名称。"""
        result = ParamGate.validate_and_normalize({"color": "RED"})
        assert result.color == "RED"

    def test_invalid_color_produces_failure(self):
        """无效颜色应产生 parse_failure。"""
        result = ParamGate.validate_and_normalize({"color": "蓝色"})
        assert result.color is None
        assert len(result.parse_failures) > 0

    def test_batch_limit_enforcement(self):
        """超过 200 个的批量应被截断或拒绝。"""
        result = ParamGate.validate_and_normalize({"fiber_refs": [str(i) for i in range(1, 250)]})
        # 应截断到 200 或产生失败
        assert len(result.fiber_ids) <= 200 or result.parse_failures

    def test_board_id_extraction(self):
        """从中文格式抽取板卡 ID。"""
        result = ParamGate.validate_and_normalize({"board_refs": ["5号盘"]})
        assert 5 in result.board_ids

    def test_port_id_extraction(self):
        """抽取端口 ID。"""
        result = ParamGate.validate_and_normalize({"port_refs": ["3号口"]})
        assert 3 in result.port_ids

    def test_empty_input(self):
        """空输入不应崩溃。"""
        result = ParamGate.validate_and_normalize({})
        assert isinstance(result, NormalizedParams)
        assert result.fiber_ids == []

    def test_multiple_fiber_ids(self):
        """多个光纤 ID。"""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["1", "2", "FIB-003"]})
        assert sorted(result.fiber_ids) == [1, 2, 3]
