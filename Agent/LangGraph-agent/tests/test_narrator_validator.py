"""
Unit tests for Narrator Validator [v7.1].

Tests the 4 programmatic validation rules:
1. Numeric values appear verbatim
2. Color words match
3. No hallucinated alarm types
4. Severity consistency
"""

import pytest

from src.nodes.narrator_validator import narrator_validator_node


class TestNarratorValidator:
    """Test NarratorValidator programmatic checks."""

    @pytest.mark.asyncio
    async def test_valid_narration_passes(self):
        """Correct narration should pass validation."""
        state = {
            "narration": "光纤1的衰耗为6.5dB，超过阈值5.0dB，状态为WARNING。",
            "rule_judgment": {
                "status": "WARNING",
                "findings": ["衰耗6.5dB超过阈值5.0dB"],
                "metrics": {"spanloss": 6.5},
                "suggested_actions": ["检查光纤连接头"],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is True

    @pytest.mark.asyncio
    async def test_numeric_tampering_fails(self):
        """Changed numeric values should fail validation."""
        state = {
            "narration": "光纤1的衰耗为3.2dB，状态正常。",  # 3.2 not in judgment
            "rule_judgment": {
                "status": "WARNING",
                "findings": ["衰耗6.5dB超过阈值5.0dB"],
                "metrics": {"spanloss": 6.5},
                "suggested_actions": [],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is False

    @pytest.mark.asyncio
    async def test_color_mismatch_fails(self):
        """Wrong color mention should fail."""
        state = {
            "narration": "光纤颜色为绿色，状态正常。",
            "rule_judgment": {
                "status": "CRITICAL",
                "findings": ["光纤颜色变为红色"],
                "metrics": {"color": "RED"},
                "suggested_actions": [],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is False

    @pytest.mark.asyncio
    async def test_severity_mismatch_fails(self):
        """Severity inconsistency should fail."""
        state = {
            "narration": "光纤状态正常，无需处理。",
            "rule_judgment": {
                "status": "CRITICAL",
                "findings": ["严重告警"],
                "metrics": {},
                "suggested_actions": ["立即处理"],
            },
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is False

    @pytest.mark.asyncio
    async def test_empty_narration_passes(self):
        """Empty narration skips validation (no judgment to validate against)."""
        state = {
            "narration": "",
            "rule_judgment": {"status": "NORMAL", "findings": [], "metrics": {}},
        }
        result = await narrator_validator_node(state)
        # Empty narration means skip validation -> pass
        assert result["narrator_validation_passed"] is True

    @pytest.mark.asyncio
    async def test_no_judgment_passes(self):
        """No judgment data means nothing to validate against."""
        state = {
            "narration": "这是一般性回复。",
            "rule_judgment": None,
        }
        result = await narrator_validator_node(state)
        assert result["narrator_validation_passed"] is True
