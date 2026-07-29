"""OutputVerificationMiddleware：after_model 输出自检 + 数据-结论一致性校验。

v3.3.0 新增：
- 检测 LLM 输出与后端数据的一致性（颜色、衰耗）
- 检测矛盾结论（如数据正常但结论说严重）
- 检测格式合规性（禁止表格、禁止单井号标题）
- 检测虚构数据（输出中出现但工具未返回的数值）
"""
from __future__ import annotations
import logging
import re
from typing import Any

from .base import Middleware, RunContext

logger = logging.getLogger("fiber.mw.output_verify")

# ── 颜色语义映射 ──
_COLOR_EMOJI_MAP = {
    "GREEN": ["🟢", "正常", "绿色", "健康"],
    "YELLOW": ["🟡", "关注", "黄色", "警告", "劣化"],
    "RED": ["🔴", "紧急", "红色", "严重", "中断"],
}

# ── 矛盾检测规则 ──
_CONTRADICTION_RULES: list[tuple[list[str], list[str], str]] = [
    # (正常指标关键词, 严重结论关键词, 告警文本)
    (["0.0 dB", "0 dB", "正常", "无告警"],
     ["严重", "中断", "紧急", "🔴"],
     "指标显示正常但结论为严重"),
    (["衰耗异常", "超出范围", "偏高"],
     ["正常", "健康", "无异常", "🟢"],
     "指标异常但结论为正常"),
]

# ── 格式违规检测 ──
_TABLE_PATTERN = re.compile(r'^\s*\|.*\|.*\|\s*$', re.MULTILINE)
_SINGLE_HASH_PATTERN = re.compile(r'^#\s+(?!#)', re.MULTILINE)

# ── 虚构数值检测 ──
_NUMERIC_PATTERN = re.compile(r'(\d+\.?\d*)\s*(?:dB|dBm)')


class OutputVerificationMiddleware(Middleware):

    async def after_model(self, ctx: RunContext, response: Any) -> None:
        if not isinstance(response, str) or not response.strip():
            return

        text = response

        # 1) 颜色一致性校验：LLM 描述的颜色是否与后端返回的颜色一致
        backend_color = ctx.meta.get("backend_color")
        if backend_color:
            llm_colors = self._extract_color_mentions(text)
            for llm_color in llm_colors:
                if not self._color_matches(backend_color, llm_color):
                    ctx.warnings.append(
                        f"⚠️ 颜色一致性告警：后端返回 {backend_color}，"
                        f"但输出中提及 '{llm_color}'，可能存在误判。")
                    logger.warning(
                        "[OutputVerify] 颜色不一致: backend=%s llm=%s",
                        backend_color, llm_color)
                    break

        # 2) 衰耗一致性校验
        backend_spanloss = ctx.meta.get("backend_spanloss")
        if backend_spanloss is not None:
            mentioned_values = _NUMERIC_PATTERN.findall(text)
            if mentioned_values:
                # 检查是否有与后端值不同的衰耗被提及
                for val_str in mentioned_values:
                    try:
                        val = float(val_str)
                        if abs(val - backend_spanloss) > 0.5:
                            ctx.warnings.append(
                                f"⚠️ 衰耗数据一致性：后端值={backend_spanloss} dB，"
                                f"输出中提及 {val} dB，请确认数据来源。")
                            logger.warning(
                                "[OutputVerify] 衰耗不一致: backend=%.2f llm=%.2f",
                                backend_spanloss, val)
                            break
                    except ValueError:
                        pass

        # 3) 矛盾结论检测
        for normal_keywords, severe_keywords, msg in _CONTRADICTION_RULES:
            has_normal = any(kw in text for kw in normal_keywords)
            has_severe = any(kw in text for kw in severe_keywords)
            if has_normal and has_severe:
                ctx.warnings.append(f"⚠️ 结论矛盾检测：{msg}")
                logger.warning("[OutputVerify] 矛盾结论: %s", msg)

        # 4) 格式合规性检查
        if _TABLE_PATTERN.search(text):
            ctx.warnings.append(
                "⚠️ 格式告警：输出包含 Markdown 表格，前端可能无法正确渲染。")
        if _SINGLE_HASH_PATTERN.search(text):
            ctx.warnings.append(
                "⚠️ 格式告警：输出包含单井号标题（#），应使用 ## 或 ###。")

        # 5) Prompt 注入防护：如果 before_model 检测到注入，检查输出是否泄露系统信息
        if ctx.meta.get("prompt_injection_detected"):
            injection_indicators = [
                "system prompt", "系统提示", "你是", "LEAD_SYSTEM",
                "config.yaml", "fiber-maintenance-agent"
            ]
            for indicator in injection_indicators:
                if indicator.lower() in text.lower():
                    ctx.warnings.append(
                        "⚠️ 安全告警：输出中可能包含系统内部信息，"
                        "疑似 Prompt 注入成功。")
                    logger.error(
                        "[OutputVerify] 疑似注入成功: 输出包含 '%s'",
                        indicator)
                    break

        logger.info("[OutputVerify] 校验完成: warnings=%d",
                     len(ctx.warnings))

    @staticmethod
    def _extract_color_mentions(text: str) -> list[str]:
        """从文本中提取颜色描述。"""
        mentions = []
        for color, indicators in _COLOR_EMOJI_MAP.items():
            for ind in indicators:
                if ind in text:
                    mentions.append(color)
                    break
        return mentions

    @staticmethod
    def _color_matches(backend_color: str, llm_color: str) -> bool:
        """判断后端颜色与 LLM 描述是否一致。"""
        if backend_color.upper() == llm_color.upper():
            return True
        # 宽松匹配：YELLOW ≈ 关注/劣化，RED ≈ 严重/中断
        return False
