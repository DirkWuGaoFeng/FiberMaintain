"""
错误归因聚合 + Pass@k / 配对显著性 —— 书籍 Ch6：从"过不过"升级为"哪里先错"。

【设计原则】
- 书籍 Ch6：单点 pass_rate 无法定位瓶颈。按"首个失败检查项"聚合，
  回答"最常在哪里先错"，把评估从总分升级为可执行的归因。
- Pass@k 采用标准无偏估计器（Codex/DeepMind 论文）：
      pass@k = 1 - C(n-c, k) / C(n, k)
  其中 n=每用例采样数，c=通过采样数，k=允许尝试次数。
- 配对显著性（McNemar 精确检验）：对比"改造前/改造后"两次评估时，
  用不一致样本对 (b, c) 判断差异是否统计显著，而非凭 pass_rate 直觉。
  b = 旧失败且新通过，c = 旧通过且新失败；二项式双侧检验。

【零 LLM】全部为纯统计计算，评估链路不新增推理成本。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Optional

# 归因报告输出条数上限（其余并入"其他"）
TOP_N = 8


def first_error_check(result: Any) -> Optional[str]:
    """从单条结果提取"首个错误检查项"名称（无失败返回 None）。

    兼容两种结果形态：
    - 带 .checks（e2e_runner.E2ECaseResult）：取首个失败检查项名
    - 带 .first_error 字符串（格式 "check: evidence"）：剥离证据前缀
    """
    checks = getattr(result, "checks", None)
    if checks:
        for c in checks:
            if not c.get("passed", True):
                return c.get("check") or "unknown"
        return None
    first_error = getattr(result, "first_error", None)
    if first_error:
        return str(first_error).split(":", 1)[0].strip()
    return None


def aggregate_first_failures(results: Iterable[Any]) -> dict:
    """按首个错误检查项聚合失败用例。

    【返回】
    {
        "total_failed": int,
        "by_check": {"intent": 3, "numbers": 2, ...},
        "top": [{"check": "...", "count": 3, "ratio": 0.43}, ...],  # 降序，含"其他"
    }
    """
    counter: Counter[str] = Counter()
    total_failed = 0
    for r in results:
        if getattr(r, "passed", True):
            continue
        total_failed += 1
        check = first_error_check(r) or "unknown"
        counter[check] += 1

    if not total_failed:
        return {"total_failed": 0, "by_check": {}, "top": []}

    ordered = counter.most_common()
    top: list[dict] = []
    for check, count in ordered[:TOP_N]:
        top.append({"check": check, "count": count, "ratio": count / total_failed})
    # 溢出归"其他"
    if len(ordered) > TOP_N:
        other = sum(c for _, c in ordered[TOP_N:])
        top.append({"check": "其他", "count": other, "ratio": other / total_failed})

    return {"total_failed": total_failed, "by_check": dict(counter), "top": top}


def error_attribution_report(results: Iterable[Any]) -> str:
    """格式化错误归因报告（Markdown）。"""
    agg = aggregate_first_failures(results)
    if not agg["total_failed"]:
        return "## 错误归因\n\n无失败用例，无需归因。"
    lines = [
        "## 错误归因（首个错误聚合）",
        "",
        f"- 失败总数: {agg['total_failed']}",
        "",
        "| 首错检查项 | 次数 | 占比 |",
        "|---|---|---|",
    ]
    for item in agg["top"]:
        lines.append(f"| {item['check']} | {item['count']} | {item['ratio']:.1%} |")
    return "\n".join(lines)


# =============================================================================
# Pass@k
# =============================================================================


def _comb(n: int, k: int) -> float:
    """组合数 C(n, k)，k<=0 或 k>n 返回 0。"""
    if k <= 0 or k > n:
        return 0.0
    return math.comb(n, k)


def pass_at_k(n: int, c: int, k: int) -> float:
    """pass@k 无偏估计：n 次采样中 c 次通过时，k 次尝试内至少一次成功的期望。

    公式（Codex 论文式 (3)）：
        pass@k = 1 - C(n-c, k) / C(n, k)
    """
    if n <= 0 or c < 0 or c > n or k <= 0:
        return 0.0
    if c == 0:
        return 0.0
    if c >= n:
        return 1.0
    if k >= n:
        # C(n-c, k)=0 当 k > n-c，此时必成功
        return 1.0
    return 1.0 - _comb(n - c, k) / _comb(n, k)


# =============================================================================
# 配对显著性（McNemar）
# =============================================================================


def mcnemar_pvalue(b: int, c: int) -> float:
    """McNemar 精确检验（双侧）p 值。

    参数：
        b = 旧失败 & 新通过（改善的样本对数）
        c = 旧通过 & 新失败（回退的样本对数）
    仅不一致对参与检验；小样本用精确二项分布，避免卡方近似失真。
    """
    total = b + c
    if total == 0:
        return 1.0  # 无不一致对 → 无证据拒绝无差异
    # 双侧：P(X >= max(b,c)) + P(X <= min(b,c))，取对称累积并截断到 1
    p = 0.0
    for x in range(0, total + 1):
        pmf = _comb(total, x) / (2**total)
        if pmf <= _comb(total, min(b, c)) / (2**total):
            p += pmf
    return min(1.0, p)


def paired_verdict(prev: Iterable[Any], curr: Iterable[Any]) -> dict:
    """改造前后两次评估的配对对比（需同用例集、同顺序）。

    【返回】
    {
        "improved": b,       # 旧失败→新通过
        "regressed": c,      # 旧通过→新失败
        "pvalue": float,
        "significant": bool, # p < 0.05
        "direction": "improved" | "regressed" | "no_change",
    }
    """
    prev_list = list(prev)
    curr_list = list(curr)
    n = min(len(prev_list), len(curr_list))
    b = c = 0
    for i in range(n):
        p_ok = bool(getattr(prev_list[i], "passed", True))
        q_ok = bool(getattr(curr_list[i], "passed", True))
        if not p_ok and q_ok:
            b += 1
        elif p_ok and not q_ok:
            c += 1

    pvalue = mcnemar_pvalue(b, c)
    if b == 0 and c == 0:
        direction = "no_change"
    elif b > c:
        direction = "improved"
    else:
        direction = "regressed"
    return {
        "improved": b,
        "regressed": c,
        "pvalue": pvalue,
        "significant": pvalue < 0.05,
        "direction": direction,
    }
