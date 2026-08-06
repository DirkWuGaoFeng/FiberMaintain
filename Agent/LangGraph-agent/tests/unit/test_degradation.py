"""
Unit tests for Degradation Manager [v7.1].

Tests:
- Five-level degradation calculation logic
- State transitions (L0-L4)
- get_status() output format
- Probe result → level mapping
"""

import pytest

from src.resilience.degradation import DegradationManager


class TestCalculateLevel:
    """Test _calculate_level() five-level logic."""

    def test_l0_all_normal(self):
        """All components available → L0."""
        dm = DegradationManager()
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 0

    def test_l1_primary_down(self):
        """14b unavailable, 7b+3b available → L1."""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": True, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 1

    def test_l2_secondary_down(self):
        """14b+7b unavailable, only 3b → L2."""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 2

    def test_l3_all_llm_down_backend_up(self):
        """All LLMs down but backend available → L3 (template mode)."""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        dm._backend_available = True
        assert dm._calculate_level() == 3

    def test_l4_all_down(self):
        """All LLMs + backend down → L4 (offline)."""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        dm._backend_available = False
        assert dm._calculate_level() == 4

    def test_l4_tertiary_down_backend_down(self):
        """3b down + backend down → L4."""
        dm = DegradationManager()
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": False}
        dm._backend_available = False
        assert dm._calculate_level() == 4

    def test_l2_tertiary_down_backend_up(self):
        """3b down but backend up → L3 (no LLM but can serve data)."""
        dm = DegradationManager()
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": False}
        dm._backend_available = True
        # tertiary=False triggers L3 path
        assert dm._calculate_level() == 3


class TestDegradationManagerState:
    """Test manager state and properties."""

    def test_initial_level_is_zero(self):
        """Manager starts at L0."""
        dm = DegradationManager()
        assert dm.current_level == 0

    def test_level_name_mapping(self):
        """Level names should be descriptive."""
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
        """get_status() returns expected structure."""
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
        """llm_status in get_status should be a copy, not reference."""
        dm = DegradationManager()
        status = dm.get_status()
        status["llm_status"]["primary"] = False
        # Original should be unchanged
        assert dm._llm_status["primary"] is True


class TestDegradationSingleton:
    """Test singleton management."""

    def test_create_and_get(self):
        """create_degradation_manager + get_degradation_manager."""
        from src.resilience.degradation import (
            create_degradation_manager,
            get_degradation_manager,
        )
        dm = create_degradation_manager()
        assert dm is not None
        assert get_degradation_manager() is dm

    def test_create_idempotent(self):
        """Multiple creates return same instance."""
        from src.resilience.degradation import create_degradation_manager
        dm1 = create_degradation_manager()
        dm2 = create_degradation_manager()
        assert dm1 is dm2


class TestDegradationTransitions:
    """Test level transition scenarios."""

    def test_gradual_degradation(self):
        """Simulate gradual component failure."""
        dm = DegradationManager()

        # Start normal
        dm._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        dm._backend_available = True
        assert dm._calculate_level() == 0

        # Primary fails
        dm._llm_status["primary"] = False
        assert dm._calculate_level() == 1

        # Secondary also fails
        dm._llm_status["secondary"] = False
        assert dm._calculate_level() == 2

        # Tertiary fails, backend still up
        dm._llm_status["tertiary"] = False
        assert dm._calculate_level() == 3

        # Backend also fails
        dm._backend_available = False
        assert dm._calculate_level() == 4

    def test_recovery_path(self):
        """Simulate recovery from L4 to L0."""
        dm = DegradationManager()
        dm._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        dm._backend_available = False
        assert dm._calculate_level() == 4

        # Backend recovers
        dm._backend_available = True
        assert dm._calculate_level() == 3

        # Tertiary recovers
        dm._llm_status["tertiary"] = True
        assert dm._calculate_level() == 2

        # Secondary recovers
        dm._llm_status["secondary"] = True
        assert dm._calculate_level() == 1

        # Primary recovers
        dm._llm_status["primary"] = True
        assert dm._calculate_level() == 0
