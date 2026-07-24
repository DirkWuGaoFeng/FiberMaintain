"""Middleware 单元测试。"""
import pytest
from src.middlewares.base import RunContext
from src.middlewares.domain_validation import FiberDomainValidationMiddleware

@pytest.mark.asyncio
async def test_ne_internal_warning():
    mw = FiberDomainValidationMiddleware()
    ctx = RunContext(session_id="test")
    result = {"data": {"src_ne_id": 101, "dst_ne_id": 101}}
    await mw.after_tool(ctx, "fiber_connection_query",
                        {"fiber_id": 1}, result)
    assert len(ctx.warnings) == 1
    assert "网元内连纤" in ctx.warnings[0]

@pytest.mark.asyncio
async def test_oop_out_of_range():
    mw = FiberDomainValidationMiddleware()
    ctx = RunContext(session_id="test")
    result = {"data": {"src_oop": -35.0, "dst_iop": -10.0}}
    await mw.after_tool(ctx, "fiber_performance_query",
                        {"fiber_id": 1}, result)
    assert any("OOP" in w for w in ctx.warnings)

@pytest.mark.asyncio
async def test_spanloss_high():
    mw = FiberDomainValidationMiddleware()
    ctx = RunContext(session_id="test")
    result = {"data": {"spanloss": 35.0}}
    await mw.after_tool(ctx, "fiber_spanloss_query",
                        {"fiber_id": 1}, result)
    assert any("异常偏高" in w for w in ctx.warnings)

@pytest.mark.asyncio
async def test_normal_no_warning():
    mw = FiberDomainValidationMiddleware()
    ctx = RunContext(session_id="test")
    result = {"data": {"src_oop": -2.0, "dst_iop": -15.0}}
    await mw.after_tool(ctx, "fiber_performance_query",
                        {"fiber_id": 1}, result)
    assert len(ctx.warnings) == 0