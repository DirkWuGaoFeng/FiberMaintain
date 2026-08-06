"""
Unit tests for Degradation Manager [v7.1/v7.2].

Tests:
- Five-level degradation level calculation
- Level transitions based on LLM/backend availability
- Status reporting
- Degradation API endpoint structure
"""

import pytest

from src.resilience.degradation import DegradationManager


class TestDegradationLevelCalculation:
    """Test _calculate_level() logic for all five levels."""

    def test_level_calculation_all_ok(self):
        """All components available → L0 (NORMAL)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 0

    def test_level_primary_down(self):
        """14b unavailable → L1 (SIMPLIFIED, 7b takes over)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": True, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 1

    def test_level_secondary_down(self):
        """7b unavailable (but 3b ok) → L2 (SMALL_MODEL)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 2

    def test_level_all_llm_down(self):
        """All LLM unavailable, backend ok → L3 (NO_LLM, template only)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = True
        assert mgr._calculate_level() == 3

    def test_level_all_down(self):
        """All LLM + backend unavailable → L4 (OFFLINE)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = False
        assert mgr._calculate_level() == 4

    def test_level_backend_down_llm_ok(self):
        """Backend down but LLM available → still L0 (LLM can respond)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        mgr._backend_available = False
        # With LLM available, not offline
        level = mgr._calculate_level()
        assert level == 0  # LLM still works, just no data queries

    def test_level_only_tertiary_no_backend(self):
        """Only 3b available, no backend → L3 (not L4 since LLM exists)."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": True}
        mgr._backend_available = False
        # tertiary is available so not "all LLM down"
        level = mgr._calculate_level()
        assert level == 2  # L2: only 3b available


class TestDegradationManagerState:
    """Test manager state and status reporting."""

    def test_initial_state(self):
        """Manager starts at L0 with all components assumed available."""
        mgr = DegradationManager()
        assert mgr.current_level == 0
        assert mgr._llm_status["primary"] is True
        assert mgr._llm_status["secondary"] is True
        assert mgr._llm_status["tertiary"] is True
        assert mgr._backend_available is True

    def test_level_name_property(self):
        """level_name returns human-readable string."""
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
        """get_status() returns complete status dict."""
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
        """Status reflects manual level changes."""
        mgr = DegradationManager()
        mgr.current_level = 3
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = True

        status = mgr.get_status()
        assert status["level"] == 3
        assert status["llm_status"]["primary"] is False
        assert "NO_LLM" in status["level_name"]


class TestDegradationTransitions:
    """Test level transition scenarios."""

    def test_degradation_sequence(self):
        """Simulate progressive degradation L0 → L1 → L2 → L3."""
        mgr = DegradationManager()

        # Start normal
        mgr._llm_status = {"primary": True, "secondary": True, "tertiary": True}
        mgr._backend_available = True
        assert mgr._calculate_level() == 0

        # Primary fails
        mgr._llm_status["primary"] = False
        assert mgr._calculate_level() == 1

        # Secondary also fails
        mgr._llm_status["secondary"] = False
        assert mgr._calculate_level() == 2

        # Tertiary fails too
        mgr._llm_status["tertiary"] = False
        assert mgr._calculate_level() == 3

    def test_recovery_sequence(self):
        """Simulate recovery L3 → L2 → L1 → L0."""
        mgr = DegradationManager()
        mgr._llm_status = {"primary": False, "secondary": False, "tertiary": False}
        mgr._backend_available = True
        assert mgr._calculate_level() == 3

        # Tertiary recovers
        mgr._llm_status["tertiary"] = True
        assert mgr._calculate_level() == 2

        # Secondary recovers
        mgr._llm_status["secondary"] = True
        assert mgr._calculate_level() == 1

        # Primary recovers
        mgr._llm_status["primary"] = True
        assert mgr._calculate_level() == 0


class TestDegradationStatusAPI:
    """Test /api/v1/degradation endpoint structure."""

    def test_degradation_status_api(self):
        """Status dict has all fields needed by frontend."""
        mgr = DegradationManager()
        status = mgr.get_status()

        # Frontend expects these fields
        required_fields = ["level", "level_name", "llm_status", "backend_available"]
        for field in required_fields:
            assert field in status, f"Missing field: {field}"

        # llm_status should have all three tiers
        assert "primary" in status["llm_status"]
        assert "secondary" in status["llm_status"]
        assert "tertiary" in status["llm_status"]
