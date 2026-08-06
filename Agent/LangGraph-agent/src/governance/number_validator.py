"""
数字模板填充 + 幻觉校验。

核心原则：LLM 不生成数字，所有数字由模板填充。
LLM 只负责生成连接词、形容词、建议性文字。
"""
from __future__ import annotations

import re
from typing import Any

# 匹配数字（含负数、小数）
_NUMBER_PATTERN = re.compile(r"-?\d+\.?\d*")


def extract_numbers(text: str) -> list[float]:
    """从文本中提取所有数字。"""
    matches = _NUMBER_PATTERN.findall(text)
    results = []
    for m in matches:
        try:
            results.append(float(m) if "." in m else int(m))
        except ValueError:
            continue
    return results


def validate_narration_numbers(narration: str, source_data: dict[str, Any]) -> list[str]:
    """
    校验 narration 中的数字是否全部来自 source_data。

    Returns:
        错误列表。空列表 = 校验通过。
    """
    narration_nums = set(extract_numbers(narration))
    # 允许的数字：source_data 中的所有数值 + 常见无害数字
    allowed: set[float] = set()
    for v in source_data.values():
        if isinstance(v, (int, float)):
            allowed.add(float(v))
        elif isinstance(v, str):
            allowed.update(float(n) for n in extract_numbers(v))
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, (int, float)):
                    allowed.add(float(item))
    # 常见无害数字（百分比、序号等）
    allowed.update({0.0, 1.0, 100.0, 2.0, 3.0, 10.0})

    hallucinated = narration_nums - allowed
    if not hallucinated:
        return []
    return [f"幻觉数字: {n} (不在源数据中)" for n in sorted(hallucinated)]


def fill_template(template: str, data: dict[str, Any]) -> str:
    """
    安全模板填充。缺失的 key 保留占位符（不报错）。
    """
    result = template
    for key, value in data.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result
