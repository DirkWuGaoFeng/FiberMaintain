"""韧性模块 [v7.1]：降级 + 健康探测。"""

from .degradation import DegradationManager, get_degradation_manager
from .health_probe import HealthProbe

__all__ = ["DegradationManager", "get_degradation_manager", "HealthProbe"]
