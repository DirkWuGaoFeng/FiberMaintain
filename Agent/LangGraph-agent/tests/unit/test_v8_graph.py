"""v8 图定义测试."""
import pytest
from unittest.mock import patch

from src.v8.graph import build_v8_graph, is_v8_mode


class TestV8Mode:
    def test_default_mode_is_not_v8(self):
        with patch.dict("os.environ", {}, clear=True):
            assert not is_v8_mode()

    def test_v8_mode_enabled(self):
        with patch.dict("os.environ", {"AGENT_MODE": "v8"}):
            assert is_v8_mode()

    def test_v8_mode_case_insensitive(self):
        with patch.dict("os.environ", {"AGENT_MODE": "V8"}):
            assert is_v8_mode()

    def test_build_v8_graph_compiles(self):
        """v8 图可以成功编译."""
        graph = build_v8_graph()
        assert graph is not None
