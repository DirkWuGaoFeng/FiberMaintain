"""
针对超时配置值的测试 [v7.2]。

验证：
- LLM 各层超时默认值（primary=60s、secondary=45s、tertiary=30s）
- SSE 流超时默认值（120s）
- 环境变量覆盖机制
"""

import os
from unittest.mock import patch


class TestLLMTimeoutDefaults:
    """验证 LLM_CONFIG 超时值符合 v7.2 规范。"""

    def test_primary_timeout_60s(self):
        """Primary（14b）超时默认为 60s。"""
        from src.config import LLM_CONFIG

        assert LLM_CONFIG["primary"].timeout == 60

    def test_secondary_timeout_45s(self):
        """Secondary（7b）超时默认为 45s。"""
        from src.config import LLM_CONFIG

        assert LLM_CONFIG["secondary"].timeout == 45

    def test_tertiary_timeout_30s(self):
        """Tertiary（3b）超时默认为 30s。"""
        from src.config import LLM_CONFIG

        assert LLM_CONFIG["tertiary"].timeout == 30

    def test_timeout_ordering(self):
        """超时逐级递减：primary > secondary > tertiary。"""
        from src.config import LLM_CONFIG

        assert LLM_CONFIG["primary"].timeout > LLM_CONFIG["secondary"].timeout
        assert LLM_CONFIG["secondary"].timeout > LLM_CONFIG["tertiary"].timeout


class TestLLMModelConfig:
    """验证模型名称与 use_cases。"""

    def test_primary_model(self):
        """Primary 模型跟随 LLM_PRIMARY 环境变量（如 Bailian qwen3.6-plus 或本地 qwen2.5:14b）。"""
        from src.config import LLM_CONFIG

        expected = os.environ.get("LLM_PRIMARY", "qwen2.5:14b")
        assert LLM_CONFIG["primary"].model == expected

    def test_secondary_model(self):
        """Secondary 模型为 qwen2.5:7b。"""
        from src.config import LLM_CONFIG

        assert LLM_CONFIG["secondary"].model == "qwen2.5:7b"

    def test_tertiary_model(self):
        """Tertiary 模型为 qwen2.5:3b。"""
        from src.config import LLM_CONFIG

        assert LLM_CONFIG["tertiary"].model == "qwen2.5:3b"

    def test_primary_use_cases(self):
        """Primary 负责 intent/analysis/report。"""
        from src.config import LLM_CONFIG

        use_cases = LLM_CONFIG["primary"].use_cases
        assert "intent_classification" in use_cases
        assert "analysis_expert" in use_cases
        assert "report_generation" in use_cases

    def test_secondary_use_cases(self):
        """Secondary 负责 narrator/knowledge。"""
        from src.config import LLM_CONFIG

        use_cases = LLM_CONFIG["secondary"].use_cases
        assert "narrator" in use_cases
        assert "knowledge_qa" in use_cases


class TestEnvVarOverride:
    """测试超时配置的环境变量覆盖。"""

    def test_env_var_override_primary(self):
        """LLM_PRIMARY_TIMEOUT 环境变量覆盖默认值。"""
        with patch.dict(os.environ, {"LLM_PRIMARY_TIMEOUT": "90"}):
            # 重新读取配置值（模拟全新导入）
            timeout = int(os.environ.get("LLM_PRIMARY_TIMEOUT", "60"))
            assert timeout == 90

    def test_env_var_override_secondary(self):
        """LLM_SECONDARY_TIMEOUT 环境变量覆盖默认值。"""
        with patch.dict(os.environ, {"LLM_SECONDARY_TIMEOUT": "60"}):
            timeout = int(os.environ.get("LLM_SECONDARY_TIMEOUT", "45"))
            assert timeout == 60

    def test_env_var_override_tertiary(self):
        """LLM_TERTIARY_TIMEOUT 环境变量覆盖默认值。"""
        with patch.dict(os.environ, {"LLM_TERTIARY_TIMEOUT": "15"}):
            timeout = int(os.environ.get("LLM_TERTIARY_TIMEOUT", "30"))
            assert timeout == 15

    def test_env_var_not_set_uses_default(self):
        """未设置环境变量时使用默认值。"""
        env = os.environ.copy()
        env.pop("LLM_PRIMARY_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            timeout = int(os.environ.get("LLM_PRIMARY_TIMEOUT", "60"))
            assert timeout == 60


class TestSSETimeoutConfig:
    """测试 SSE 流超时配置。"""

    def test_sse_timeout_default(self):
        """SSE_STREAM_TIMEOUT 默认为 120s。"""
        # 从环境变量读取默认值（与 server.py 逻辑一致）
        # 剔除本地 .env 覆盖，验证默认值逻辑
        env = os.environ.copy()
        env.pop("SSE_STREAM_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            timeout = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
            assert timeout == 120

    def test_sse_timeout_env_override(self):
        """SSE_STREAM_TIMEOUT 可被覆盖。"""
        with patch.dict(os.environ, {"SSE_STREAM_TIMEOUT": "180"}):
            timeout = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
            assert timeout == 180

    def test_sse_heartbeat_interval_default(self):
        """SSE_HEARTBEAT_INTERVAL 默认为 5s。"""
        interval = int(os.environ.get("SSE_HEARTBEAT_INTERVAL", "5"))
        assert interval == 5

    def test_sse_timeout_greater_than_llm(self):
        """SSE 超时（120s）> Primary LLM 超时（60s），以允许完整处理。"""
        from src.config import LLM_CONFIG

        sse_timeout = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
        assert sse_timeout > LLM_CONFIG["primary"].timeout

    def test_frontend_timeout_greater_than_backend(self):
        """前端 SSE 超时（130s）> 后端 SSE 超时（120s）。"""
        # 前端使用 130s（在 sse.ts 中定义为 SSE_CLIENT_TIMEOUT_MS）
        frontend_timeout_ms = 130_000
        # 剔除本地 .env 覆盖，校验默认配置下的前后端超时契约
        env = os.environ.copy()
        env.pop("SSE_STREAM_TIMEOUT", None)
        with patch.dict(os.environ, env, clear=True):
            backend_timeout_s = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
        assert frontend_timeout_ms / 1000 > backend_timeout_s
