"""
Threshold Engine — 唯一阈值查表入口。

从 config/thresholds.yaml 加载阈值，提供纤类感知的阈值查询。
所有消费方（rule_judgment、Skill YAML、Prompt 注入）统一从此处获取阈值。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_THRESHOLDS_PATH = Path(__file__).parent.parent.parent / "config" / "thresholds.yaml"


@dataclass(frozen=True)
class ThresholdResult:
    """阈值查询结果。"""

    warning: float
    critical: float
    source: str  # 来源说明（用于审计）


@dataclass(frozen=True)
class JudgmentResult:
    """阈值判断结果。"""

    status: str  # NORMAL / WARNING / CRITICAL
    value: float
    threshold_warning: float
    threshold_critical: float
    percent_over: float  # 超出阈值百分比（正常时为 0）


class ThresholdEngine:
    """阈值查表引擎（单例，启动时加载 YAML）。"""

    def __init__(self, config_path: Path | None = None):
        path = config_path or _THRESHOLDS_PATH
        with open(path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        self._link_rules: list[dict] = self._config["link_spanloss"]
        self._default: dict = self._config["default_spanloss"]
        op = self._config["optical_power"]
        self.oop_range: tuple[float, float] = (op["OOP"]["min"], op["OOP"]["max"])
        self.iop_range: tuple[float, float] = (op["IOP"]["min"], op["IOP"]["max"])
        logger.info(f"[ThresholdEngine] Loaded from {path}")

    def get_spanloss_threshold(
        self, fiber_type: Optional[str] = None, link_length_km: Optional[float] = None
    ) -> ThresholdResult:
        """查询链路总衰耗阈值。纤类/长度未知时返回默认值。"""
        if link_length_km is not None:
            for rule in self._link_rules:
                if link_length_km <= rule["max_length_km"]:
                    return ThresholdResult(
                        warning=rule["warning"],
                        critical=rule["critical"],
                        source=f"link_spanloss(≤{rule['max_length_km']}km)",
                    )
        return ThresholdResult(
            warning=self._default["warning"],
            critical=self._default["critical"],
            source="default_spanloss",
        )

    def judge_spanloss(
        self,
        value: float,
        fiber_type: Optional[str] = None,
        link_length_km: Optional[float] = None,
    ) -> JudgmentResult:
        """判断 spanloss 值的状态。"""
        th = self.get_spanloss_threshold(fiber_type, link_length_km)
        if value > th.critical:
            status = "CRITICAL"
            percent = (value - th.warning) / th.warning * 100
        elif value > th.warning:
            status = "WARNING"
            percent = (value - th.warning) / th.warning * 100
        else:
            status = "NORMAL"
            percent = 0.0
        return JudgmentResult(
            status=status,
            value=value,
            threshold_warning=th.warning,
            threshold_critical=th.critical,
            percent_over=round(percent, 1),
        )

    def judge_oop(self, value: float) -> str:
        """判断 OOP 是否在正常范围。"""
        if self.oop_range[0] <= value <= self.oop_range[1]:
            return "NORMAL"
        return "WARNING"

    def judge_iop(self, value: float) -> str:
        """判断 IOP 是否在正常范围。"""
        if self.iop_range[0] <= value <= self.iop_range[1]:
            return "NORMAL"
        return "WARNING"


# =============================================================================
# 全局单例
# =============================================================================

_engine: Optional[ThresholdEngine] = None


def get_threshold_engine() -> ThresholdEngine:
    """获取全局 ThresholdEngine 单例。"""
    global _engine
    if _engine is None:
        _engine = ThresholdEngine()
    return _engine
