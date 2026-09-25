"""
降级管理器单元测试 [v7.1/v7.2]。

测试：
- 五级降级等级计算
- 基于 LLM/后端可用性的等级转换
- 状态报告
- 降级 API 端点结构
"""

from src.resilience.degradation import DegradationManager


class TestDegradationLevelCalculation:
    """测试 _calculate_level() 在全部五个等级下的逻辑。"""

    def test_level_calculation_all_ok(self):
        """所有组件可用 → L0 (NORMAL)。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 0

    def test_level_primary_down(self):
        """14b 不可用 → L1 (SIMPLIFIED, 7b 接管)。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": True, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 1

    def test_level_secondary_down(self):
        """7b 不可用（但 3b 可用）→ L2 (SMALL_MODEL)。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 2

    def test_level_all_llm_down(self):
        """所有 LLM 不可用、后端可用 → L3 (NO_LLM, 仅模板)。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = True
        assert mgr._calculate_level() == 3

    def test_level_all_down(self):
        """所有 LLM + 后端均不可用 → L4 (OFFLINE)。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = False
        assert mgr._calculate_level() == 4

    def test_level_backend_down_llm_ok(self):
        """后端不可用但 LLM 可用 → 仍为 L0（LLM 可响应）。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        mgr._backend_available = False
        # LLM 可用时并非离线
        level = mgr._calculate_level()
        assert level == 0  # LLM 仍可工作，只是无法进行数据查询

    def test_level_only_tertiary_no_backend(self):
        """仅有 3b 可用、无后端 → L3（因存在 LLM 故非 L4）。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": True}
        mgr._backend_available = False
        # tertiary 可用，因此不算"所有 LLM 不可用"
        level = mgr._calculate_level()
        assert level == 2  # L2: 仅有 3b 可用


class TestDegradationManagerState:
    """测试管理器状态与状态报告。"""

    def test_initial_state(self):
        """管理器初始为 L0，假定所有组件可用。"""
        mgr = DegradationManager()
        assert mgr.current_level == 0
        assert mgr._llm_status["primary"] is True
        assert mgr._llm_status["secondary"] is True
        assert mgr._llm_status["tertiary"] is True
        assert mgr._backend_available is True

    def test_level_name_property(self):
        """level_name 返回可读字符串。"""
        mgr = DegradationManager()
        mgr.current_level = 0
        assert "NORMAL" in mgr.level_name

        mgr.current_level = 1
        assert "SIMPLIFIED" in mgr.level_name

        mgr.current_level = 2
        assert "SMALL_MODEL" in mgr.level_name

        mgr.current_level = 3
        assert "NO_LLM" in mgr.level_name

        mgr.current_level = 4
        assert "OFFLINE" in mgr.level_name

    def test_get_status_structure(self):
        """get_status() 返回完整的状态字典。"""
        mgr = DegradationManager()
        status = mgr.get_status()

        assert "level" in status
        assert "level_name" in status
        assert "llm_status" in status
        assert "backend_available" in status
        assert "last_probe" in status

        assert status["level"] == 0
        assert status["llm_status"]["primary"] is True
        assert status["backend_available"] is True

    def test_get_status_reflects_changes(self):
        """状态反映手动修改的等级。"""
        mgr = DegradationManager()
        mgr.current_level = 3
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = True

        status = mgr.get_status()
        assert status["level"] == 3
        assert status["llm_status"]["primary"] is False
        assert "NO_LLM" in status["level_name"]


class TestDegradationTransitions:
    """测试等级转换场景。"""

    def test_degradation_sequence(self):
        """模拟渐进式降级 L0 → L1 → L2 → L3。"""
        mgr = DegradationManager()

        # 初始正常
        mgr._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 0

        # Primary 故障
        mgr._llm_status["primary"] = False
        assert mgr._calculate_level() == 1

        # Secondary 也故障
        mgr._llm_status["secondary"] = False
        assert mgr._calculate_level() == 2

        # Tertiary 也故障
        mgr._llm_status["tertiary"] = False
        assert mgr._calculate_level() == 3

    def test_recovery_sequence(self):
        """模拟恢复 L3 → L2 → L1 → L0。"""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = True
        assert mgr._calculate_level() == 3

        # Tertiary 恢复
        mgr._llm_status["tertiary"] = True
        assert mgr._calculate_level() == 2

        # Secondary 恢复
        mgr._llm_status["secondary"] = True
        assert mgr._calculate_level() == 1

        # Primary 恢复
        mgr._llm_status["primary"] = True
        assert mgr._calculate_level() == 0


class TestDegradationStatusAPI:
    """测试 /api/v1/degradation 端点结构。"""

    def test_degradation_status_api(self):
        """状态字典包含前端所需的全部字段。"""
        mgr = DegradationManager()
        status = mgr.get_status()

        # 前端期望这些字段
        required_fields = ["level", "level_name", "llm_status", "backend_available"]
        for field in required_fields:
            assert field in status, f"Missing field: {field}"

        # llm_status 应包含全部三个层级
        assert "primary" in status["llm_status"]
        assert "secondary" in status["llm_status"]
        assert "tertiary" in status["llm_status"]
