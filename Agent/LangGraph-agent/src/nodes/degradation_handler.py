"""
Degradation handler node: implements L3 rule-based and L4 pure-RAG fallback.
"""

from __future__ import annotations

import logging

from ..graph.state import FiberAgentState

logger = logging.getLogger(__name__)

# L3 templates for common scenarios
L3_TEMPLATES = {
    "single_query": """## Fiber Query Result (Offline Mode)

The system is currently unable to perform real-time analysis.
Please check the backend service status and try again.

For urgent matters, contact the on-call engineer.
""",
    "batch_query": """## Batch Query Result (Offline Mode)

Batch processing is temporarily unavailable.
Please try querying fibers individually.
""",
    "spanloss_analysis": """## Span Loss Analysis (Offline Mode)

Real-time span loss analysis is unavailable.
Reference thresholds:
- GREEN: < 0.3 dB (normal)
- YELLOW: 0.3 - 0.5 dB (warning)
- RED: > 0.5 dB (critical)
""",
    "color_diagnosis": """## Color Diagnosis (Offline Mode)

Color diagnosis is temporarily unavailable.
Color definitions:
- GREEN: Normal operation
- YELLOW: Approaching threshold
- RED: Critical, requires immediate attention
""",
    "health_check": """## Health Check (Offline Mode)

System health check is unavailable.
Please check backend service connectivity.
""",
}


async def degradation_handler_node(state: FiberAgentState) -> dict:
    """
    Degradation handler: provides fallback responses when LLM or backend is unavailable.

    L3: Rule-based template output (white-list scenarios)
    L4: Pure RAG mode (only knowledge base, no LLM)
    """
    level = state.get("degradation_level", "L1")
    intent = state.get("intent")

    if level == "L3":
        intent_type = intent.intent if intent else "single_query"
        template = L3_TEMPLATES.get(intent_type)
        if template:
            # Try to fill in data if available
            fiber_data = state.get("fiber_data", {})
            if fiber_data and "total" in fiber_data:
                template += f"\n\nLast known stats: {fiber_data.get('total', 'N/A')} total fibers."
            return {"final_report": template}
        else:
            return {"final_report": "System is in degraded mode. This query type is not supported offline."}

    elif level == "L4":
        # Pure RAG mode: use knowledge base only
        rag_context = state.get("rag_context", [])
        if rag_context:
            answer = "\n\n---\n\n".join(rag_context[:3])
            return {
                "final_report": f"## Knowledge Base Response (Offline Mode)\n\n{answer}"
            }
        else:
            return {
                "final_report": "System is fully offline. Knowledge base is unavailable. Please check system status."
            }

    # L1/L2: no degradation needed
    return {}
