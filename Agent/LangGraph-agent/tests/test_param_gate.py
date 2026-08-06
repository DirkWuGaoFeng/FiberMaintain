"""
Unit tests for ParamGate [v7.1].

Tests Layer 2 parameter validation:
- Format conversion (FIB-XXXX → int, N号盘 → int, N口 → int)
- Color mapping
- Time parsing
- Batch limit validation
"""

import pytest

from src.nodes.param_gate import ParamGate
from src.graph.state import NormalizedParams


class TestParamGate:
    """Test ParamGate parameter normalization."""

    def test_fiber_id_numeric(self):
        """Extract numeric fiber ID."""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["1"]})
        assert isinstance(result, NormalizedParams)
        assert result.fiber_ids == [1]
        assert not result.parse_failures

    def test_fiber_id_fib_format(self):
        """Extract FIB-XXXX format."""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["FIB-0001"]})
        assert 1 in result.fiber_ids

    def test_fiber_id_chinese_format(self):
        """Extract Chinese format '13号光纤'."""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["13号光纤"]})
        assert 13 in result.fiber_ids

    def test_color_mapping_chinese(self):
        """Map Chinese color names."""
        result = ParamGate.validate_and_normalize({"color": "红色"})
        assert result.color == "RED"

    def test_color_mapping_english(self):
        """Map English color names."""
        result = ParamGate.validate_and_normalize({"color": "RED"})
        assert result.color == "RED"

    def test_invalid_color_produces_failure(self):
        """Invalid color should produce parse_failure."""
        result = ParamGate.validate_and_normalize({"color": "蓝色"})
        assert result.color is None
        assert len(result.parse_failures) > 0

    def test_batch_limit_enforcement(self):
        """Batch over 200 should be truncated or rejected."""
        result = ParamGate.validate_and_normalize({
            "fiber_refs": [str(i) for i in range(1, 250)]
        })
        # Should either truncate to 200 or produce failure
        assert len(result.fiber_ids) <= 200 or result.parse_failures

    def test_board_id_extraction(self):
        """Extract board ID from Chinese format."""
        result = ParamGate.validate_and_normalize({"board_refs": ["5号盘"]})
        assert 5 in result.board_ids

    def test_port_id_extraction(self):
        """Extract port ID."""
        result = ParamGate.validate_and_normalize({"port_refs": ["3号口"]})
        assert 3 in result.port_ids

    def test_empty_input(self):
        """Empty input should not crash."""
        result = ParamGate.validate_and_normalize({})
        assert isinstance(result, NormalizedParams)
        assert result.fiber_ids == []

    def test_multiple_fiber_ids(self):
        """Multiple fiber IDs."""
        result = ParamGate.validate_and_normalize({"fiber_refs": ["1", "2", "FIB-003"]})
        assert sorted(result.fiber_ids) == [1, 2, 3]
