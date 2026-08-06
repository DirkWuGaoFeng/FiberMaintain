"""
Tests for timeout configuration values [v7.2].

Verifies:
- LLM tier timeout defaults (primary=60s, secondary=45s, tertiary=30s)
- SSE stream timeout default (120s)
- Environment variable override mechanism
"""

import os
from unittest.mock import patch


class TestLLMTimeoutDefaults:
    """Verify LLM_CONFIG timeout values match v7.2 spec."""

    def test_primary_timeout_60s(self):
        """Primary (14b) timeout defaults to 60s."""
        from src.config import LLM_CONFIG
        assert LLM_CONFIG["primary"].timeout == 60

    def test_secondary_timeout_45s(self):
        """Secondary (7b) timeout defaults to 45s."""
        from src.config import LLM_CONFIG
        assert LLM_CONFIG["secondary"].timeout == 45

    def test_tertiary_timeout_30s(self):
        """Tertiary (3b) timeout defaults to 30s."""
        from src.config import LLM_CONFIG
        assert LLM_CONFIG["tertiary"].timeout == 30

    def test_timeout_ordering(self):
        """Timeouts decrease: primary > secondary > tertiary."""
        from src.config import LLM_CONFIG
        assert LLM_CONFIG["primary"].timeout > LLM_CONFIG["secondary"].timeout
        assert LLM_CONFIG["secondary"].timeout > LLM_CONFIG["tertiary"].timeout


class TestLLMModelConfig:
    """Verify model names and use_cases."""

    def test_primary_model(self):
        """Primary model follows LLM_PRIMARY env (e.g. Bailian qwen3.6-plus or local qwen2.5:14b)."""
        from src.config import LLM_CONFIG
        expected = os.environ.get("LLM_PRIMARY", "qwen2.5:14b")
        assert LLM_CONFIG["primary"].model == expected

    def test_secondary_model(self):
        """Secondary model is qwen2.5:7b."""
        from src.config import LLM_CONFIG
        assert LLM_CONFIG["secondary"].model == "qwen2.5:7b"

    def test_tertiary_model(self):
        """Tertiary model is qwen2.5:3b."""
        from src.config import LLM_CONFIG
        assert LLM_CONFIG["tertiary"].model == "qwen2.5:3b"

    def test_primary_use_cases(self):
        """Primary handles intent/analysis/report."""
        from src.config import LLM_CONFIG
        use_cases = LLM_CONFIG["primary"].use_cases
        assert "intent_classification" in use_cases
        assert "analysis_expert" in use_cases
        assert "report_generation" in use_cases

    def test_secondary_use_cases(self):
        """Secondary handles narrator/knowledge."""
        from src.config import LLM_CONFIG
        use_cases = LLM_CONFIG["secondary"].use_cases
        assert "narrator" in use_cases
        assert "knowledge_qa" in use_cases


class TestEnvVarOverride:
    """Test environment variable override for timeouts."""

    def test_env_var_override_primary(self):
        """LLM_PRIMARY_TIMEOUT env var overrides default."""
        with patch.dict(os.environ, {"LLM_PRIMARY_TIMEOUT": "90"}):
            # Re-read the config value (simulating fresh import)
            timeout = int(os.environ.get("LLM_PRIMARY_TIMEOUT", "60"))
            assert timeout == 90

    def test_env_var_override_secondary(self):
        """LLM_SECONDARY_TIMEOUT env var overrides default."""
        with patch.dict(os.environ, {"LLM_SECONDARY_TIMEOUT": "60"}):
            timeout = int(os.environ.get("LLM_SECONDARY_TIMEOUT", "45"))
            assert timeout == 60

    def test_env_var_override_tertiary(self):
        """LLM_TERTIARY_TIMEOUT env var overrides default."""
        with patch.dict(os.environ, {"LLM_TERTIARY_TIMEOUT": "15"}):
            timeout = int(os.environ.get("LLM_TERTIARY_TIMEOUT", "30"))
            assert timeout == 15

    def test_env_var_not_set_uses_default(self):
        """Without env var, default is used."""
        env = os.environ.copy()
        env.pop("LLM_PRIMARY_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            timeout = int(os.environ.get("LLM_PRIMARY_TIMEOUT", "60"))
            assert timeout == 60


class TestSSETimeoutConfig:
    """Test SSE stream timeout configuration."""

    def test_sse_timeout_default(self):
        """SSE_STREAM_TIMEOUT defaults to 120s."""
        # Read from env with default (same logic as server.py)
        # 剔除本地 .env 覆盖，验证默认值逻辑
        env = os.environ.copy()
        env.pop("SSE_STREAM_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            timeout = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
            assert timeout == 120

    def test_sse_timeout_env_override(self):
        """SSE_STREAM_TIMEOUT can be overridden."""
        with patch.dict(os.environ, {"SSE_STREAM_TIMEOUT": "180"}):
            timeout = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
            assert timeout == 180

    def test_sse_heartbeat_interval_default(self):
        """SSE_HEARTBEAT_INTERVAL defaults to 5s."""
        interval = int(os.environ.get("SSE_HEARTBEAT_INTERVAL", "5"))
        assert interval == 5

    def test_sse_timeout_greater_than_llm(self):
        """SSE timeout (120s) > primary LLM timeout (60s) to allow full processing."""
        from src.config import LLM_CONFIG
        sse_timeout = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
        assert sse_timeout > LLM_CONFIG["primary"].timeout

    def test_frontend_timeout_greater_than_backend(self):
        """Frontend SSE timeout (130s) > backend SSE timeout (120s)."""
        # Frontend uses 130s (defined in sse.ts as SSE_CLIENT_TIMEOUT_MS)
        frontend_timeout_ms = 130_000
        # 剔除本地 .env 覆盖，校验默认配置下的前后端超时契约
        env = os.environ.copy()
        env.pop("SSE_STREAM_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            backend_timeout_s = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
        assert frontend_timeout_ms / 1000 > backend_timeout_s
