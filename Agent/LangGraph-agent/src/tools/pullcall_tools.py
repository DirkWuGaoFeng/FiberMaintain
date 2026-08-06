"""
Pull-Call tools: create, poll, cancel pull-call sessions [v7.1].

Pull-call is the process of remotely requesting a field technician
to perform fiber testing (OTDR trace, power measurement).

Maps to C++ API Gateway endpoints:
  - POST   /api/v1/pullcall/create
  - GET    /api/v1/pullcall/{session_id}/status
  - DELETE /api/v1/pullcall/{session_id}
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ._http_client import assert_positive_int, fiber_http_client, make_error_json
from .confirmation_gate import get_confirmation_gate

# =============================================================================
# Input Schemas
# =============================================================================

class PullCallCreateInput(BaseModel):
    fiber_id: int = Field(description="Target fiber ID to test")
    test_type: str = Field(
        default="OTDR",
        description="Test type: OTDR / POWER / VISUAL",
    )
    priority: str = Field(default="NORMAL", description="Priority: LOW / NORMAL / HIGH")
    confirm_token: Optional[str] = Field(
        default=None,
        description="User confirmation token; without it the write is only registered as pending",
    )


class PullCallPollInput(BaseModel):
    session_id: str = Field(description="Pull-call session ID returned by create")


class PullCallCancelInput(BaseModel):
    session_id: str = Field(description="Pull-call session ID to cancel")
    reason: Optional[str] = Field(default=None, description="Cancellation reason")
    confirm_token: Optional[str] = Field(
        default=None,
        description="User confirmation token; without it the write is only registered as pending",
    )


def _pending_confirmation_json(operation: str, params: dict, description: str) -> str:
    """Register a write intent and ask the user to confirm [P1-B]."""
    entry = get_confirmation_gate().request(operation, params, description)
    if entry is None:
        return make_error_json(
            "CONFIRM_QUEUE_FULL", "待确认写操作过多", "请先处理已有的待确认操作"
        )
    return json.dumps(
        {
            "status": "pending_confirmation",
            "confirm_token": entry["token"],
            "operation": operation,
            "description": description,
            "message": "这是写操作，需要用户确认。请向用户展示确认卡片，"
            "确认后将携带 confirm_token 重新调用。",
        },
        ensure_ascii=False,
    )


def _consume_confirmation(
    confirm_token: Optional[str], operation: str, params: dict
) -> Optional[str]:
    """Validate and consume a confirmation token. Returns error JSON or None."""
    entry = get_confirmation_gate().confirm(confirm_token)
    if entry is None:
        return make_error_json(
            "CONFIRMATION_INVALID", "确认令牌无效或已过期", "请重新发起操作获取新令牌"
        )
    if entry["operation"] != operation or entry["params"] != params:
        return make_error_json(
            "CONFIRMATION_MISMATCH", "确认令牌与操作不匹配", "令牌只能用于其登记的操作"
        )
    return None


# =============================================================================
# Pull-Call Tools
# =============================================================================

@tool(args_schema=PullCallCreateInput)
async def pull_call_create(
    fiber_id: int,
    test_type: str = "OTDR",
    priority: str = "NORMAL",
    confirm_token: Optional[str] = None,
) -> str:
    """Create a pull-call session to request field fiber testing.
    WRITE OPERATION [P1-B]: without confirm_token this only registers a
    pending confirmation; the backend is called only after user consent.
    Returns: JSON with session_id/status, or pending_confirmation + token."""
    # Layer 3 assertion
    assert_positive_int(fiber_id, "fiber_id")
    assert test_type in ("OTDR", "POWER", "VISUAL"), f"Invalid test_type: {test_type}"

    params = {"fiber_id": fiber_id, "test_type": test_type, "priority": priority}
    if not confirm_token:
        return _pending_confirmation_json(
            "pull_call_create",
            params,
            f"对光纤 {fiber_id} 发起 {test_type} 测试（优先级 {priority}）",
        )
    error = _consume_confirmation(confirm_token, "pull_call_create", params)
    if error:
        return error

    try:
        return await fiber_http_client.post(
            "/api/v1/pullcall/create",
            json=params,
            timeout=5.0,
        )
    except Exception as e:
        return make_error_json("PULLCALL_CREATE_FAILED", str(e), "确认光纤ID和测试类型")


@tool(args_schema=PullCallPollInput)
async def pull_call_poll(session_id: str) -> str:
    """Poll pull-call session status (PENDING/IN_PROGRESS/COMPLETED/FAILED).
    Returns: JSON with session_id, status, progress, result(if completed)."""
    assert session_id, "session_id cannot be empty"

    try:
        return await fiber_http_client.get(
            f"/api/v1/pullcall/{session_id}/status",
            timeout=3.0,
        )
    except Exception as e:
        return make_error_json("PULLCALL_POLL_FAILED", str(e), "确认会话ID是否有效")


@tool(args_schema=PullCallCancelInput)
async def pull_call_cancel(
    session_id: str,
    reason: Optional[str] = None,
    confirm_token: Optional[str] = None,
) -> str:
    """Cancel an active pull-call session.
    WRITE OPERATION [P1-B]: requires user confirmation, same as create.
    Returns: JSON with cancellation confirmation, or pending_confirmation."""
    assert session_id, "session_id cannot be empty"

    params = {"session_id": session_id, "reason": reason}
    if not confirm_token:
        return _pending_confirmation_json(
            "pull_call_cancel",
            params,
            f"取消拉纤会话 {session_id}" + (f"（原因: {reason}）" if reason else ""),
        )
    error = _consume_confirmation(confirm_token, "pull_call_cancel", params)
    if error:
        return error

    try:
        req_params = {}
        if reason:
            req_params["reason"] = reason
        return await fiber_http_client.delete(
            f"/api/v1/pullcall/{session_id}",
            timeout=3.0,
            params=req_params if req_params else None,
        )
    except Exception as e:
        return make_error_json("PULLCALL_CANCEL_FAILED", str(e), "会话可能已完成或不存在")
