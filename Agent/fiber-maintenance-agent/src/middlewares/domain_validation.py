"""FiberDomainValidationMiddleware：after_tool 领域规则校验（§5.2）。"""
from __future__ import annotations
from typing import Any

from .base import Middleware, RunContext

OOP_RANGE = (-30.0, 10.0)
IOP_RANGE = (-40.0, 5.0)
SPANLOSS_RANGE = (0.0, 30.0)

class FiberDomainValidationMiddleware(Middleware):

    async def after_tool(self, ctx: RunContext, tool_name: str,
                         args: dict, result: Any) -> None:
        if not isinstance(result, dict):
            return
        data = result.get("data", result)

        # 1) 网元间连纤校验
        if tool_name in ("fiber_connection_query",):
            src, dst = data.get("src_ne_id"), data.get("dst_ne_id")
            if src is not None and dst is not None and src == dst:
                ctx.warnings.append(
                    f"⚠️ F{args.get('fiber_id')} 为网元内连纤"
                    f"（src_ne_id == dst_ne_id == {src}），"
                    f"本系统仅处理网元间连纤，分析结论可能不适用。")

        # 2) 光功率范围校验
        if tool_name == "fiber_performance_query":
            oop, iop = data.get("src_oop"), data.get("dst_iop")
            if oop is not None and not (OOP_RANGE[0] <= oop <= OOP_RANGE[1]):
                ctx.warnings.append(
                    f"⚠️ F{args.get('fiber_id')} OOP={oop} dBm 超出正常范围"
                    f" {OOP_RANGE}，数据可能异常。")
            if iop is not None and not (IOP_RANGE[0] <= iop <= IOP_RANGE[1]):
                ctx.warnings.append(
                    f"⚠️ F{args.get('fiber_id')} IOP={iop} dBm 超出正常范围"
                    f" {IOP_RANGE}，数据可能异常。")

        # 3) 衰耗范围校验
        if tool_name == "fiber_spanloss_query":
            sl = data.get("spanloss")
            if sl is not None and sl > SPANLOSS_RANGE[1]:
                ctx.warnings.append(
                    f"⚠️ F{args.get('fiber_id')} 衰耗={sl} dB 异常偏高"
                    f"（> {SPANLOSS_RANGE[1]} dB），疑似链路严重劣化或中断。")
            elif sl is not None and sl < SPANLOSS_RANGE[0]:
                ctx.warnings.append(
                    f"⚠️ F{args.get('fiber_id')} 衰耗={sl} dB 为负值，"
                    f"疑似采集数据错误。")