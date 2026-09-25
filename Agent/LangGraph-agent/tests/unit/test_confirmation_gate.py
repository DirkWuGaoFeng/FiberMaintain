"""
写操作确认门控（Confirmation Gate）单元测试 [改进清单 P1-B]。

测试：
- ConfirmationGate 生命周期：请求 → 确认一次性消费
- TTL 过期、未知 token、待处理队列上限
- pull_call_create/cancel 门控：无 token 不会到达后端，
  有效 token 执行，参数不匹配被拒绝
"""

import json
from unittest.mock import AsyncMock

import pytest

from src.tools import pullcall_tools
from src.tools.confirmation_gate import ConfirmationGate


@pytest.fixture
def gate():
    return ConfirmationGate(ttl_seconds=600, max_pending=3)


class TestConfirmationGate:
    def test_request_then_confirm(self, gate):
        entry = gate.request("pull_call_create", {"fiber_id": 5}, "发起测试")
        assert entry is not None
        assert entry["token"]
        assert gate.list_pending()[0]["operation"] == "pull_call_create"

        confirmed = gate.confirm(entry["token"])
        assert confirmed is not None
        assert confirmed["params"] == {"fiber_id": 5}
        assert gate.list_pending() == []

    def test_confirm_is_one_shot(self, gate):
        entry = gate.request("op", {}, "desc")
        assert gate.confirm(entry["token"]) is not None
        assert gate.confirm(entry["token"]) is None

    def test_confirm_unknown_token(self, gate):
        assert gate.confirm("nonexistent") is None

    def test_ttl_expiry(self, gate):
        entry = ConfirmationGate(ttl_seconds=0).request("op", {}, "desc")
        assert ConfirmationGate(ttl_seconds=0).confirm(entry["token"]) is None

        # 同一实例：过期后 list_pending 也不返回
        expired_gate = ConfirmationGate(ttl_seconds=0)
        expired_gate.request("op", {}, "desc")
        assert expired_gate.list_pending() == []

    def test_max_pending_cap(self, gate):
        for i in range(3):
            assert gate.request(f"op{i}", {}, "desc") is not None
        assert gate.request("op_full", {}, "desc") is None


class TestPullCallGating:
    @pytest.fixture
    def wired(self, gate, monkeypatch):
        """独立 gate + 记录式 HTTP mock，保证测试互不污染."""
        monkeypatch.setattr(pullcall_tools, "get_confirmation_gate", lambda: gate)
        post = AsyncMock(return_value='{"session_id": "S-1", "status": "PENDING"}')
        delete = AsyncMock(return_value='{"status": "CANCELLED"}')
        monkeypatch.setattr(pullcall_tools.fiber_http_client, "post", post)
        monkeypatch.setattr(pullcall_tools.fiber_http_client, "delete", delete)
        return gate, post, delete

    async def test_create_without_token_only_registers(self, wired):
        gate, post, _ = wired
        result = json.loads(await pullcall_tools.pull_call_create.ainvoke({"fiber_id": 5, "test_type": "OTDR"}))
        assert result["status"] == "pending_confirmation"
        assert result["confirm_token"]
        post.assert_not_called()  # 无 token 不打后端
        assert len(gate.list_pending()) == 1

    async def test_create_with_valid_token_executes(self, wired):
        gate, post, _ = wired
        pending = json.loads(await pullcall_tools.pull_call_create.ainvoke({"fiber_id": 5, "test_type": "OTDR"}))
        result = json.loads(
            await pullcall_tools.pull_call_create.ainvoke(
                {"fiber_id": 5, "test_type": "OTDR", "confirm_token": pending["confirm_token"]}
            )
        )
        assert result["session_id"] == "S-1"
        post.assert_called_once()
        assert gate.list_pending() == []  # 一次性消费

    async def test_create_with_tampered_params_rejected(self, wired):
        gate, post, _ = wired
        pending = json.loads(await pullcall_tools.pull_call_create.ainvoke({"fiber_id": 5, "test_type": "OTDR"}))
        # 篡改 fiber_id 复用令牌
        result = json.loads(
            await pullcall_tools.pull_call_create.ainvoke(
                {"fiber_id": 999, "test_type": "OTDR", "confirm_token": pending["confirm_token"]}
            )
        )
        assert result["error_code"] == "CONFIRMATION_MISMATCH"
        post.assert_not_called()

    async def test_create_with_invalid_token_rejected(self, wired):
        _, post, _ = wired
        result = json.loads(await pullcall_tools.pull_call_create.ainvoke({"fiber_id": 5, "confirm_token": "bogus"}))
        assert result["error_code"] == "CONFIRMATION_INVALID"
        post.assert_not_called()

    async def test_cancel_gate_flow(self, wired):
        gate, _, delete = wired
        pending = json.loads(await pullcall_tools.pull_call_cancel.ainvoke({"session_id": "S-1"}))
        assert pending["status"] == "pending_confirmation"
        delete.assert_not_called()

        result = json.loads(
            await pullcall_tools.pull_call_cancel.ainvoke(
                {"session_id": "S-1", "confirm_token": pending["confirm_token"]}
            )
        )
        assert result["status"] == "CANCELLED"
        delete.assert_called_once()
