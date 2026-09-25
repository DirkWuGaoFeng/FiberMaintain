"""
拉纤工具集 —— 创建、轮询、取消拉纤会话 [v7.1]。

拉纤是远程请求现场技术人员执行光纤测试（OTDR 轨迹、功率测量）的过程。

对应 C++ API Gateway 接口：
  - POST   /api/v1/pullcall/create
  - GET    /api/v1/pullcall/{session_id}/status
  - DELETE /api/v1/pullcall/{session_id}
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ..security.tool_reviewer import get_tool_reviewer
from ._http_client import assert_positive_int, fiber_http_client, make_error_json
from .confirmation_gate import get_confirmation_gate

logger = logging.getLogger(__name__)

# =============================================================================
# 输入参数契约（Input Schemas）
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
    """注册写意图并请求用户确认 [P1-B]。

    【服务端独立复核 [v7.4]】在进入前端确认面板前，先经 ToolReviewer
    做参数类型/高风险约束的服务端复核（提案者-审核者分离，书籍 Ch4）。
    复核不通过 → 拒绝进入确认流程，返回 block 错误。
    """
    # 服务端独立复核：在 confirmation_gate（用户确认）之前
    review = get_tool_reviewer().review(operation, params)
    if not review.is_allow:
        logger.warning(
            f"[PullCallTools] Reviewer blocked {operation}: " f"{review.reason} violations={review.violations}"
        )
        detail = "；".join(review.violations) or review.reason
        return make_error_json("REVIEW_BLOCKED", "服务端复核未通过", f"参数不符合安全策略：{detail}")

    entry = get_confirmation_gate().request(operation, params, description)
    if entry is None:
        return make_error_json("CONFIRM_QUEUE_FULL", "待确认写操作过多", "请先处理已有的待确认操作")
    return json.dumps(
        {
            "status": "pending_confirmation",
            "confirm_token": entry["token"],
            "operation": operation,
            "description": description,
            "message": "这是写操作，需要用户确认。请向用户展示确认卡片，" "确认后将携带 confirm_token 重新调用。",
        },
        ensure_ascii=False,
    )


def _consume_confirmation(confirm_token: Optional[str], operation: str, params: dict) -> Optional[str]:
    """校验并消费一个确认令牌。返回错误 JSON 或 None。"""
    entry = get_confirmation_gate().confirm(confirm_token)
    if entry is None:
        return make_error_json("CONFIRMATION_INVALID", "确认令牌无效或已过期", "请重新发起操作获取新令牌")
    if entry["operation"] != operation or entry["params"] != params:
        return make_error_json("CONFIRMATION_MISMATCH", "确认令牌与操作不匹配", "令牌只能用于其登记的操作")
    return None


# =============================================================================
# 拉纤工具（Pull-Call Tools）
# =============================================================================


@tool(args_schema=PullCallCreateInput)
async def pull_call_create(
    fiber_id: int,
    test_type: str = "OTDR",
    priority: str = "NORMAL",
    confirm_token: Optional[str] = None,
) -> str:
    """创建拉纤会话以请求现场光纤测试。
    写操作 [P1-B]：无 confirm_token 时仅登记待确认；
    仅在用户确认后才调用后端。
    返回：JSON，含 session_id/status，或 pending_confirmation + token。"""
    # Layer 3 断言
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
    """轮询拉纤会话状态（PENDING/IN_PROGRESS/COMPLETED/FAILED）。
    返回：JSON，含 session_id、status、progress、result（如已完成）。"""
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
    """取消一个进行中的拉纤会话。
    写操作 [P1-B]：与创建一样需要用户确认。
    返回：JSON，含取消确认信息，或 pending_confirmation。"""
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
