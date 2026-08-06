"""
Sub-graphs for the main orchestration graph [v7.1].

- data_collector: ReAct Agent + ToolNode (唯一绑定后端 API Tool 的组件)
- knowledge_assistant: RAG 检索 + LLM 问答
- proactive: 主动诊断子图 (事件触发, 全自动)
"""

from .data_collector import data_collector_subgraph
from .knowledge_assistant import knowledge_assistant_subgraph

__all__ = [
    "data_collector_subgraph",
    "knowledge_assistant_subgraph",
]
