"""
Phase 3.6: 容错降级引擎

四级降级策略：
L1 正常: primary 模型 + 全量工具
L2 模型降级: primary → fallback → fast（已有 ModelDegradationMiddleware 处理）
L3 规则兜底: 白名单场景用规则引擎直接回答（scene=1 单纤查询, scene=2-case-b 颜色判定）
L4 纯知识模式: 仅返回 RAG 知识片段 + 提示用户后端不可用
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fiber.fallback")


# ============================================================
#  规则引擎 — L3 白名单场景
# ============================================================

@dataclass
class RuleResult:
    """规则引擎返回结果。"""
    handled: bool
    response: str = ""
    data: dict = field(default_factory=dict)


class RuleEngine:
    """规则兜底引擎：白名单场景可直接回答，无需 LLM。

    白名单:
    - scene=1: 单纤性能查询 → 直接返回阈值判断
    - scene=2-case-b: 颜色判定 → 直接返回颜色状态
    """

    # 颜色阈值标准 (dB)
    COLOR_THRESHOLDS = {
        "green":  (0.0, 5.0),    # 正常
        "yellow": (5.0, 10.0),   # 告警
        "orange": (10.0, 15.0),  # 严重
        "red":    (15.0, 30.0),  # 紧急
    }

    # 光功率正常范围 (dBm)
    OOP_RANGE = (-30.0, 10.0)
    IOP_RANGE = (-40.0, 5.0)

    def try_handle(self, scene: str, context: dict) -> RuleResult:
        """尝试用规则处理，返回 RuleResult。"""
        if scene == "scene_1" or scene == "1":
            return self._handle_single_fiber(context)
        if scene == "scene_2b" or scene == "2-case-b":
            return self._handle_color_judge(context)
        return RuleResult(handled=False)

    def _handle_single_fiber(self, ctx: dict) -> RuleResult:
        """Scene 1: 单纤性能 → 阈值判断。"""
        perf = ctx.get("performance", {})
        if not perf:
            return RuleResult(handled=False)

        fiber_id = ctx.get("fiber_id", "?")
        oop = perf.get("src_oop")
        iop = perf.get("dst_iop")
        spanloss = perf.get("spanloss")

        issues: list[str] = []
        if oop is not None and not (self.OOP_RANGE[0] <= oop <= self.OOP_RANGE[1]):
            issues.append(f"OOP={oop} dBm 超出正常范围 {self.OOP_RANGE}")
        if iop is not None and not (self.IOP_RANGE[0] <= iop <= self.IOP_RANGE[1]):
            issues.append(f"IOP={iop} dBm 超出正常范围 {self.IOP_RANGE}")
        if spanloss is not None and spanloss > 15.0:
            issues.append(f"衰耗={spanloss} dB 异常偏高")

        if issues:
            resp = (f"光纤 F{fiber_id} 存在异常：\n"
                    + "\n".join(f"- {i}" for i in issues)
                    + "\n\n⚠️ 当前为规则兜底模式（L3），建议联系运维人员进一步排查。")
        else:
            resp = (f"光纤 F{fiber_id} 各项指标正常"
                    f"（OOP={oop}, IOP={iop}, 衰耗={spanloss} dB）。\n"
                    f"⚠️ 当前为规则兜底模式（L3），仅供参考。")

        return RuleResult(
            handled=True, response=resp,
            data={"fiber_id": fiber_id, "issues": issues})

    def _handle_color_judge(self, ctx: dict) -> RuleResult:
        """Scene 2-case-b: 颜色判定 → 阈值匹配。"""
        spanloss = ctx.get("spanloss")
        fiber_id = ctx.get("fiber_id", "?")

        if spanloss is None:
            return RuleResult(handled=False)

        color = "unknown"
        for c, (lo, hi) in self.COLOR_THRESHOLDS.items():
            if lo <= spanloss < hi:
                color = c
                break
        if spanloss >= 30.0:
            color = "red"

        color_cn = {"green": "绿色(正常)", "yellow": "黄色(告警)",
                    "orange": "橙色(严重)", "red": "红色(紧急)"}.get(color, "未知")

        resp = (f"光纤 F{fiber_id} 衰耗={spanloss} dB，"
                f"颜色状态: {color_cn}。\n"
                f"⚠️ 当前为规则兜底模式（L3），仅供参考。")

        return RuleResult(
            handled=True, response=resp,
            data={"fiber_id": fiber_id, "color": color,
                  "spanloss": spanloss})


# ============================================================
#  FallbackEngine — 四级降级主控
# ============================================================

@dataclass
class FallbackContext:
    """降级上下文。"""
    degradation_level: int = 0          # 0=L1, 1=L2, 2=L3, 3=L4
    backend_available: bool = True
    llm_available: bool = True
    rag_available: bool = True
    scene: str = ""
    extra: dict = field(default_factory=dict)


class FallbackEngine:
    """四级降级引擎。

    L1 正常: 全链路可用
    L2 模型降级: LLM 不可用 → 降级模型（由 ModelDegradationMiddleware 处理）
    L3 规则兜底: 模型全部不可用 → 白名单场景规则引擎
    L4 纯知识模式: 后端也不可用 → 仅返回 RAG 知识 + 提示
    """

    def __init__(self):
        self._rule_engine = RuleEngine()

    def decide_level(self, ctx: FallbackContext) -> int:
        """根据当前状态决定应使用的降级等级。"""
        if ctx.llm_available and ctx.backend_available:
            return 0  # L1 正常

        if ctx.llm_available and not ctx.backend_available:
            return 1  # L2 模型可用但后端不可用 → 降级模型继续

        if not ctx.llm_available and ctx.backend_available:
            return 2  # L3 模型全不可用 → 规则兜底

        return 3  # L4 全不可用 → 纯知识模式

    async def handle(self, scene: str, user_message: str,
                     context: dict | None = None,
                     knowledge_snippets: list[dict] | None = None,
                     ) -> tuple[int, str, dict]:
        """主入口：返回 (level, response_text, metadata)。"""
        ctx_data = context or {}
        snippets = knowledge_snippets or []

        # 确定降级等级
        fb_ctx = FallbackContext(
            backend_available=ctx_data.get("backend_available", True),
            llm_available=ctx_data.get("llm_available", True),
            scene=scene,
            extra=ctx_data,
        )
        level = self.decide_level(fb_ctx)

        if level <= 1:
            # L1/L2: 正常或模型降级，由主流程处理
            return level, "", {"fallback": False}

        if level == 2:
            # L3: 规则兜底
            result = self._rule_engine.try_handle(scene, ctx_data)
            if result.handled:
                logger.info("Fallback L3: 规则引擎处理 scene=%s", scene)
                return 2, result.response, {
                    "fallback": True, "level": "L3_rule",
                    "data": result.data}

            # 白名单外场景 → 升级到 L4
            level = 3

        # L4: 纯知识模式
        return self._handle_knowledge_mode(snippets, user_message)

    def _handle_knowledge_mode(self, snippets: list[dict],
                                user_message: str) -> tuple[int, str, dict]:
        """L4: 纯知识模式 — 返回 RAG 知识片段 + 提示。"""
        if not snippets:
            resp = ("⚠️ 当前系统处于降级模式（L4），LLM 和后端服务均不可用。\n"
                    "暂无相关知识可供参考，请稍后重试或联系运维人员。")
            return 3, resp, {"fallback": True, "level": "L4_knowledge"}

        # 组装知识片段
        parts = ["⚠️ 系统当前处于知识模式（L4），以下信息仅供参考：\n"]
        for i, s in enumerate(snippets[:5], 1):
            content = s.get("content", s.get("text", ""))[:500]
            source = s.get("source", "知识库")
            parts.append(f"**[{i}] {source}**\n{content}\n")

        parts.append("\n以上为系统缓存的历史知识，非实时分析结果。")

        logger.info("Fallback L4: 返回 %d 条知识片段", len(snippets[:5]))
        return 3, "\n".join(parts), {
            "fallback": True, "level": "L4_knowledge",
            "snippet_count": len(snippets[:5])}
