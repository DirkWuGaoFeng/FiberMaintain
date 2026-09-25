"""
降级管理器单元测试 [v7.1]。

测试：
- 五级降级等级计算逻辑
- 状态转换（L0-L4）
- get_status() 输出格式
- 探测结果 → 等级映射
"""

from src.resilience.degradation import DegradationManager


class TestCalculateLevel:
    """测试 _calculate_level() 五级逻辑。"""

    def test_l0_all_normal(self):
        """所有组件可用 → L0。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 0

    def test_l1_primary_down(self):
        """14b 不可用，7b+3b 可用 → L1。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": True, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 1

    def test_l2_secondary_down(self):
        """14b+7b 不可用，仅 3b → L2。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 2

    def test_l3_all_llm_down_backend_up(self):
        """所有 LLM 不可用但后端可用 → L3（模板模式）。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        dm._backend_available = True
        assert dm._calculate_level() == 3

    def test_l4_all_down(self):
        """所有 LLM + 后端不可用 → L4（离线）。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        dm._backend_available = False
        assert dm._calculate_level() == 4

    def test_l4_tertiary_down_backend_down(self):
        """3b 不可用 + 后端不可用 → L4。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": False}
        dm._backend_available = False
        assert dm._calculate_level() == 4

    def test_l2_tertiary_down_backend_up(self):
        """3b 不可用但后端可用 → L3（无 LLM 但仍可提供数据）。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": False}
        dm._backend_available = True
        # tertiary=False 触发 L3 路径
        assert dm._calculate_level() == 3


class TestDegradationManagerState:
    """测试管理器状态与属性。"""

    def test_initial_level_is_zero(self):
        """管理器从 L0 开始。"""
        dm = DegradationManager()
        assert dm.current_level == 0

    def test_level_name_mapping(self):
        """等级名称应具有描述性。"""
        dm = DegradationManager()
        dm.current_level = 0
        assert "NORMAL" in dm.level_name
        dm.current_level = 1
        assert "SIMPLIFIED" in dm.level_name
        dm.current_level = 2
        assert "SMALL_MODEL" in dm.level_name
        dm.current_level = 3
        assert "NO_LLM" in dm.level_name
        dm.current_level = 4
        assert "OFFLINE" in dm.level_name

    def test_get_status_format(self):
        """get_status() 返回预期的结构。"""
        dm = DegradationManager()
        status = dm.get_status()
        assert "level" in status
        assert "level_name" in status
        assert "llm_status" in status
        assert "backend_available" in status
        assert "last_probe" in status
        assert status["level"] == 0
        assert status["backend_available"] is True

    def test_get_status_llm_status_copy(self):
        """get_status 中的 llm_status 应为副本而非引用。"""
        dm = DegradationManager()
        status = dm.get_status()
        status["llm_status"]["primary"] = False
        # 原对象应保持不变
        assert dm._llm_status["primary"] is True


class TestDegradationSingleton:
    """测试单例管理。"""

    def test_create_and_get(self):
        """create_degradation_manager + get_degradation_manager。"""
        from src.resilience.degradation import (
            create_degradation_manager,
            get_degradation_manager,
        )

        dm = create_degradation_manager()
        assert dm is not None
        assert get_degradation_manager() is dm

    def test_create_idempotent(self):
        """多次创建返回同一实例。"""
        from src.resilience.degradation import create_degradation_manager

        dm1 = create_degradation_manager()
        dm2 = create_degradation_manager()
        assert dm1 is dm2


class TestDegradationTransitions:
    """测试等级转换场景。"""

    def test_gradual_degradation(self):
        """模拟组件逐步故障。"""
        dm = DegradationManager()

        # 初始正常
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 0

        # Primary 故障
        dm._llm_status["primary"] = False
        assert dm._calculate_level() == 1

        # Secondary 也故障
        dm._llm_status["secondary"] = False
        assert dm._calculate_level() == 2

        # Tertiary 故障，后端仍可用
        dm._llm_status["tertiary"] = False
        assert dm._calculate_level() == 3

        # 后端也故障
        dm._backend_available = False
        assert dm._calculate_level() == 4

    def test_recovery_path(self):
        """模拟从 L4 恢复到 L0。"""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        dm._backend_available = False
        assert dm._calculate_level() == 4

        # 后端恢复
        dm._backend_available = True
        assert dm._calculate_level() == 3

        # Tertiary 恢复
        dm._llm_status["tertiary"] = True
        assert dm._calculate_level() == 2

        # Secondary 恢复
        dm._llm_status["secondary"] = True
        assert dm._calculate_level() == 1

        # Primary 恢复
        dm._llm_status["primary"] = True
        assert dm._calculate_level() == 0
