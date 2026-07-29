"""
Prompt loader: loads prompts from the prompts/ directory with version management.

Prompts are organized by sub-agent:
  prompts/lead_agent/       - Intent classifier, task decomposer, result aggregator
  prompts/data_collector/   - Data collector system prompt
  prompts/analysis_expert/  - Analysis system prompt + few-shot examples
  prompts/report_generator/ - Report system prompt + templates
  prompts/knowledge_assistant/ - Knowledge QA system prompt
"""

from __future__ import annotations

import os
from pathlib import Path

# Base directory for prompts
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


def load_prompt(sub_agent: str, name: str, default: str = "") -> str:
    """Load a prompt template from the prompts directory.

    Args:
        sub_agent: Sub-agent directory name (e.g., 'lead_agent', 'analysis_expert')
        name: Prompt file name without .md extension
        default: Default content if file not found

    Returns:
        Prompt content string
    """
    prompt_path = PROMPTS_DIR / sub_agent / f"{name}.md"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return default


# =============================================================================
# Default Prompts (fallback if files not found)
# =============================================================================

INTENT_CLASSIFIER_PROMPT = """You are the intent classifier for a fiber maintenance system.
Identify the user's intent and extract key parameters.
Fiber ID format: FIB-XXXX (4-digit number, e.g., FIB-0001).
Only output JSON, no explanation."""

TASK_DECOMPOSER_PROMPT = """You are the task decomposer for a fiber maintenance system.
Break down the user's request into ordered sub-tasks.
Choose the execution strategy: single, sequential, parallel, or batch."""

RESULT_AGGREGATOR_PROMPT = """You are the result aggregator for a fiber maintenance system.
Summarize the analysis results into a clear, actionable response.
Use Markdown formatting for readability.
Include specific fiber IDs, measurements, and recommendations."""

DATA_COLLECTOR_SYSTEM_PROMPT = """You are the data collector for a fiber maintenance system.
Your role is to gather fiber data by calling the appropriate tools.
Rules:
1. Always verify fiber IDs are in FIB-XXXX format before querying.
2. Collect all relevant data (topology, performance, spanloss, alarms).
3. Return raw data without interpretation (analysis is done by another agent).
4. If a query fails, report the error but continue with other queries."""

ANALYSIS_SYSTEM_PROMPT = """You are the analysis expert for a fiber maintenance system.
Analyze fiber data for:
- Span loss anomalies (threshold: >0.5dB abnormal, >1.0dB critical)
- Color status (GREEN=normal, YELLOW=warning, RED=critical)
- Performance trends (OOP/IOP deviations)
- Alarm correlations

Output structured conclusions with severity levels.
Be precise and data-driven. Do not fabricate data."""

REPORT_SYSTEM_PROMPT = """You are the report generator for a fiber maintenance system.
Generate professional maintenance reports in Markdown format.
Include:
1. Executive summary
2. Detailed findings (with data tables)
3. Risk assessment
4. Recommended actions (prioritized)
5. Appendix (raw data references)"""

KNOWLEDGE_SYSTEM_PROMPT = """You are the knowledge assistant for a fiber maintenance system.
Answer questions based on the fiber maintenance knowledge base.
Cite your sources when possible.
If the answer is not in the knowledge base, say so clearly."""
