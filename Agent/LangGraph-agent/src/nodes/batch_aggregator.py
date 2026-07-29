"""
Batch aggregator node: merges all chunk results into a summary.
"""

from __future__ import annotations

import json
import logging
import math

from ..graph.state import FiberAgentState

logger = logging.getLogger(__name__)


def batch_aggregator_node(state: FiberAgentState) -> dict:
    """
    Aggregator node: merges all chunk results (already merged by operator.add reducer).
    Performs layered aggregation:
      Layer 1: Programmatic statistics (zero tokens)
      Layer 2: Anomaly filtering (zero tokens)
      Layer 3: Summary assembly (~3500 tokens -> passed to analysis_expert)
    """
    all_results = state.get("batch_results", [])
    if not all_results:
        logger.warning("[BatchAggregator] No results to aggregate")
        return {
            "fiber_data": {"total": 0, "normal": 0, "abnormal": 0},
            "batch_progress": {"completed": 0, "total": 0, "percentage": 0},
        }

    # Layer 1: Statistical aggregation
    total = sum(r.get("count", 0) for r in all_results if isinstance(r, dict))
    normal = sum(r.get("normal_count", 0) for r in all_results if isinstance(r, dict))
    abnormal = total - normal

    # Layer 2: Color distribution and spanloss stats
    all_data = []
    for r in all_results:
        if isinstance(r, dict):
            all_data.extend(r.get("results", []))

    color_dist = {"GREEN": 0, "YELLOW": 0, "RED": 0}
    spanloss_values = []
    red_fibers = []

    for item in all_data:
        if not isinstance(item, dict):
            continue
        # Count colors if present
        color = item.get("color", "").upper()
        if color in color_dist:
            color_dist[color] += 1
        # Collect spanloss values
        sl = item.get("spanloss")
        if sl is not None:
            try:
                spanloss_values.append(float(sl))
            except (ValueError, TypeError):
                pass
        # Track red fibers
        fid = item.get("fiber_id")
        if color == "RED" and fid:
            red_fibers.append(str(fid))

    # Spanloss statistics
    spanloss_stats = {}
    if spanloss_values:
        spanloss_stats = {
            "mean": round(sum(spanloss_values) / len(spanloss_values), 3),
            "max": round(max(spanloss_values), 3),
            "min": round(min(spanloss_values), 3),
            "count": len(spanloss_values),
        }

    # Layer 3: Assemble summary
    summary = {
        "total": total,
        "normal": normal,
        "abnormal": abnormal,
        "color_distribution": color_dist,
        "spanloss_stats": spanloss_stats,
        "red_fibers": red_fibers[:50],  # Cap at 50
        "top_anomalies": all_data[:10],  # Top 10 for LLM analysis
    }

    logger.info(f"[BatchAggregator] Total={total}, Normal={normal}, Abnormal={abnormal}")

    return {
        "fiber_data": summary,
        "batch_progress": {
            "completed": len(all_results),
            "total": len(all_results),
            "percentage": 100,
        },
    }
