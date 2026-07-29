"""FiberDomainValidationMiddleware：意图预分类 + 参数校验与自纠正 + 领域规则校验（§5.2）。

v3.3.0 增强：
- before_model: 基于关键词的意图预分类 + fiber_id 主动提取注入 ctx.meta
- before_tool: fiber_id 格式自纠正（提取数字）, 批量查询上限 200
- after_tool: 光功率/衰耗/连纤拓扑范围校验
"""
from __future__ import annotations
import logging
import re
from typing import Any

from .base import Middleware, RunContext

logger = logging.getLogger("fiber.mw.validation")

OOP_RANGE = (-30.0, 10.0)
IOP_RANGE = (-40.0, 5.0)
SPANLOSS_RANGE = (0.0, 30.0)

# fiber_id 格式：正整数
_FIBER_ID_RE = re.compile(r"^\d+$")
# 从用户输入中提取 fiber_id（支持 F65、光纤65、F-65 等变体）
_FIBER_ID_EXTRACT_RE = re.compile(
    r"(?:F|光纤|FIBER|fib(?:er)?)\s*-?\s*(\d+)", re.IGNORECASE)
# 从用户输入中提取 fiber_id 范围（如 F65~F75、65到75、65-75）
_FIBER_RANGE_RE = re.compile(
    r"(\d+)\s*[~\-–到至]\s*(\d+)")
BATCH_LIMIT = 200

# 需要校验 fiber_id 的工具
_FIBER_ID_TOOLS = {
    "fiber_performance_query", "fiber_spanloss_query",
    "fiber_connection_query", "fiber_trend_query",
    "fiber_color_diagnosis", "batch_fiber_performance_query",
    "batch_fiber_spanloss_query",
}

# 批量查询工具
_BATCH_TOOLS = {
    "batch_fiber_performance_query", "batch_fiber_spanloss_query",
}

# ── 意图预分类关键词映射 ──
_INTENT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("single_fiber_analysis",
     ["分析", "查看", "检查", "看看", "查询", "诊断", "状态",
      "F", "光纤", "连纤", "光功率", "衰耗"]),
    ("batch_analysis",
     ["批量", "多条", "所有", "全部", "~", "到", "至",
      "一批", "这些光纤", "这些连纤"]),
    ("trend_query",
     ["趋势", "变化", "走势", "历史", "过去", "统计",
      "最近", "对比"]),
    ("health_check",
     ["巡检", "健康", "网元", "健康检查", "状态检查"]),
    ("report_export",
     ["报告", "导出", "PDF", "Excel", "CSV", "报表"]),
    ("knowledge_qa",
     ["什么是", "怎么", "如何", "为什么", "原理", "规范",
      "标准", "阈值", "告警含义"]),
]


class FiberDomainValidationMiddleware(Middleware):

    # ────────────────────────────────────────────────
    # before_model: 意图预分类 + fiber_id 主动提取
    # ────────────────────────────────────────────────
    async def before_model(self, ctx: RunContext) -> None:
        user_msgs = [m for m in ctx.messages if m.get("role") == "user"]
        if not user_msgs:
            return
        text = user_msgs[-1].get("content", "")

        # 1) 意图预分类
        detected_intents: list[str] = []
        for intent, keywords in _INTENT_KEYWORDS:
            if any(kw in text for kw in keywords):
                detected_intents.append(intent)
        if detected_intents:
            ctx.meta["detected_intents"] = detected_intents
            logger.info("[Validation] 意图预分类: %s", detected_intents)

        # 2) fiber_id 主动提取
        extracted_ids: list[int] = []
        for m in _FIBER_ID_EXTRACT_RE.finditer(text):
            fid = int(m.group(1))
            if 1 <= fid <= 99999:
                extracted_ids.append(fid)
        # 范围提取（如 F65~F75 → [65,66,...,75]）
        for m in _FIBER_RANGE_RE.finditer(text):
            start, end = int(m.group(1)), int(m.group(2))
            if 1 <= start <= end <= 99999 and (end - start) < BATCH_LIMIT:
                extracted_ids = list(range(start, end + 1))
                break  # 范围优先于单独提取
        if extracted_ids:
            ctx.meta["extracted_fiber_ids"] = extracted_ids
            logger.info("[Validation] 提取 fiber_ids: %s",
                        extracted_ids if len(extracted_ids) <= 10
                        else f"{extracted_ids[:5]}...({len(extracted_ids)}条)")

    # ────────────────────────────────────────────────
    # before_tool: 参数自纠正（替代纯告警）
    # ────────────────────────────────────────────────
    async def before_tool(self, ctx: RunContext, tool_name: str,
                          args: dict) -> None:
        # 1) fiber_id 格式自纠正：尝试提取数字部分
        if tool_name in _FIBER_ID_TOOLS:
            fid = args.get("fiber_id")
            if fid is not None:
                fid_str = str(fid).strip()
                if not _FIBER_ID_RE.match(fid_str):
                    # 尝试自动修复：提取数字部分
                    digits = re.sub(r"[^0-9]", "", fid_str)
                    if digits and 1 <= int(digits) <= 99999:
                        logger.warning(
                            "[Validation] fiber_id 自纠正: '%s' → %s",
                            fid, digits)
                        args["fiber_id"] = int(digits)
                        ctx.warnings.append(
                            f"⚠️ fiber_id='{fid}' 已自动修正为 {digits}")
                    else:
                        ctx.warnings.append(
                            f"⚠️ fiber_id='{fid}' 格式无效且无法修正，"
                            f"工具调用将失败。")

        # 2) 批量查询参数自纠正
        if tool_name in _BATCH_TOOLS:
            fiber_ids = args.get("fiber_ids", [])
            if isinstance(fiber_ids, list):
                # 清理非整数元素
                cleaned = []
                for fid in fiber_ids:
                    fid_str = re.sub(r"[^0-9]", "", str(fid))
                    if fid_str.isdigit() and 1 <= int(fid_str) <= 99999:
                        cleaned.append(int(fid_str))
                if len(cleaned) != len(fiber_ids):
                    logger.info(
                        "[Validation] 批量 fiber_ids 清洗: %d → %d",
                        len(fiber_ids), len(cleaned))
                    args["fiber_ids"] = cleaned
                # 上限截断
                if len(cleaned) > BATCH_LIMIT:
                    ctx.warnings.append(
                        f"⚠️ 批量查询数量 {len(cleaned)} 超过上限 "
                        f"{BATCH_LIMIT}，将截断处理。")
                    args["fiber_ids"] = cleaned[:BATCH_LIMIT]

    # ────────────────────────────────────────────────
    # after_tool: 领域规则校验
    # ────────────────────────────────────────────────
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

        # 4) 颜色一致性记录（供 after_model 输出校验使用）
        if tool_name == "colored_fibers_query":
            color = data.get("color")
            if color:
                ctx.meta["backend_color"] = color
                logger.info("[Validation] 记录后端颜色: %s", color)
        if tool_name == "fiber_performance_query":
            spanloss = data.get("spanloss")
            if spanloss is not None:
                ctx.meta["backend_spanloss"] = spanloss
