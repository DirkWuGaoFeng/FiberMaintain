"""Threshold Engine 单元测试 — 验证纤类感知阈值查表。"""
import pytest

from src.governance.threshold_engine import ThresholdEngine, ThresholdResult, JudgmentResult


@pytest.fixture
def engine():
    return ThresholdEngine()


class TestSpanlossThreshold:
    def test_default_threshold_when_fiber_type_unknown(self, engine):
        result = engine.get_spanloss_threshold(fiber_type=None, link_length_km=None)
        assert result.warning == 5.0
        assert result.critical == 8.0
        assert result.source == "default_spanloss"

    def test_short_link(self, engine):
        result = engine.get_spanloss_threshold(fiber_type="G.652", link_length_km=8.0)
        assert result.warning == 6.0
        assert result.critical == 8.0

    def test_medium_link(self, engine):
        result = engine.get_spanloss_threshold(fiber_type="G.652", link_length_km=30.0)
        assert result.warning == 16.0
        assert result.critical == 20.0

    def test_long_link(self, engine):
        result = engine.get_spanloss_threshold(fiber_type="G.652", link_length_km=50.0)
        assert result.warning == 28.0
        assert result.critical == 35.0

    def test_very_long_link(self, engine):
        result = engine.get_spanloss_threshold(fiber_type="G.652", link_length_km=100.0)
        assert result.warning == 35.0
        assert result.critical == 42.0


class TestOpticalPower:
    def test_oop_range(self, engine):
        assert engine.oop_range == (-10.0, 3.0)

    def test_iop_range(self, engine):
        assert engine.iop_range == (-25.0, -5.0)

    def test_oop_normal(self, engine):
        assert engine.judge_oop(-5.0) == "NORMAL"

    def test_oop_abnormal(self, engine):
        assert engine.judge_oop(-12.0) == "WARNING"

    def test_iop_normal(self, engine):
        assert engine.judge_iop(-15.0) == "NORMAL"

    def test_iop_abnormal(self, engine):
        assert engine.judge_iop(-30.0) == "WARNING"


class TestJudgeSpanloss:
    def test_normal(self, engine):
        result = engine.judge_spanloss(3.2, fiber_type="G.652", link_length_km=8.0)
        assert result.status == "NORMAL"
        assert result.percent_over == 0.0

    def test_warning(self, engine):
        result = engine.judge_spanloss(7.0, fiber_type="G.652", link_length_km=8.0)
        assert result.status == "WARNING"
        assert result.percent_over > 0

    def test_critical(self, engine):
        result = engine.judge_spanloss(9.0, fiber_type="G.652", link_length_km=8.0)
        assert result.status == "CRITICAL"

    def test_default_fallback(self, engine):
        result = engine.judge_spanloss(6.0)
        assert result.status == "WARNING"
        assert result.threshold_warning == 5.0
