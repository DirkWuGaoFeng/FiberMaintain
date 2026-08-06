"""
Proactive Diagnosis Sub-graph [v7.1].

Event-triggered automatic diagnosis (no user interaction):
  EventTrigger → QuickCollect → AutoAnalyze → Alert

Timeout: 10s total. Fully automatic.
Triggered by: CRITICAL alarm, GREEN→RED color change.
"""

from __future__ import annotations

import asyncio
import logging
import time

from ...config import SPANLOSS_THRESHOLD

logger = logging.getLogger(__name__)

PROACTIVE_TIMEOUT = 10.0  # seconds


async def run_proactive_diagnosis(event: dict, reason: str = "") -> dict:
    """
    Run proactive diagnosis for an event.

    Args:
        event: The triggering event dict
        reason: Why this was triggered (critical_alarm / color_escalation)

    Returns:
        Diagnosis result dict
    """
    start_time = time.time()
    fiber_id = event.get("fiber_id")

    logger.info(f"[Proactive] Starting diagnosis for fiber {fiber_id} (reason: {reason})")

    result = {
        "fiber_id": fiber_id,
        "trigger": reason,
        "status": "UNKNOWN",
        "findings": [],
        "alert_message": None,
        "duration_ms": 0,
    }

    try:
        # Wrap with timeout
        diagnosis = await asyncio.wait_for(
            _diagnose(fiber_id, event),
            timeout=PROACTIVE_TIMEOUT,
        )
        result.update(diagnosis)
    except asyncio.TimeoutError:
        result["status"] = "TIMEOUT"
        result["findings"].append("诊断超时（10s），请手动检查")
        logger.warning(f"[Proactive] Diagnosis timeout for fiber {fiber_id}")
    except Exception as e:
        result["status"] = "ERROR"
        result["findings"].append(f"诊断异常: {e}")
        logger.error(f"[Proactive] Diagnosis error: {e}")

    result["duration_ms"] = int((time.time() - start_time) * 1000)

    # Generate alert message if critical
    if result["status"] == "CRITICAL":
        result["alert_message"] = (
            f"⚠️ 主动诊断告警：光纤 {fiber_id} 检测到严重异常！\n"
            f"发现：{'；'.join(result['findings'])}\n"
            f"触发原因：{reason}"
        )
        logger.warning(f"[Proactive] ALERT: {result['alert_message']}")

    return result


async def _diagnose(fiber_id: int | None, event: dict) -> dict:
    """Internal diagnosis logic: QuickCollect → AutoAnalyze."""
    findings = []
    status = "NORMAL"

    if not fiber_id:
        return {"status": "ERROR", "findings": ["事件中缺少 fiber_id"]}

    # QuickCollect: get performance + spanloss
    from ...tools._http_client import fiber_http_client

    try:
        perf_raw = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/performance", timeout=3.0)
        import json
        perf = json.loads(perf_raw)

        oop = perf.get("src_oop")
        iop = perf.get("dst_iop")
        if oop is not None:
            findings.append(f"OOP={oop}dBm")
        if iop is not None:
            findings.append(f"IOP={iop}dBm")
    except Exception as e:
        findings.append(f"性能查询失败: {e}")

    try:
        span_raw = await fiber_http_client.get(f"/api/v1/fibers/{fiber_id}/spanloss", timeout=3.0)
        import json
        span = json.loads(span_raw)
        spanloss = span.get("spanloss")
        if spanloss is not None:
            findings.append(f"衰耗={spanloss}dB")
            if spanloss > SPANLOSS_THRESHOLD:
                status = "CRITICAL"
                findings.append(f"衰耗超标（阈值{SPANLOSS_THRESHOLD}dB）")
            elif spanloss > SPANLOSS_THRESHOLD * 0.7:
                status = "WARNING"
    except Exception as e:
        findings.append(f"衰耗查询失败: {e}")

    # AutoAnalyze: simple threshold-based (zero LLM for speed)
    if not findings:
        findings.append("无法获取诊断数据")
        status = "WARNING"

    return {"status": status, "findings": findings}
