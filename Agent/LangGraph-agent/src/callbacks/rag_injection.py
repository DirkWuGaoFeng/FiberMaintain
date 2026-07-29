"""
RAG injection callback: auto-injects knowledge context before LLM calls
in analysis and report generation nodes.
"""

from __future__ import annotations

import logging

from langchain_core.callbacks import BaseCallbackHandler

logger = logging.getLogger(__name__)


class RAGInjectionCallback(BaseCallbackHandler):
    """
    RAG injection callback: retrieves and injects knowledge context
    into prompts for analysis_expert and report_generator nodes.
    """

    def __init__(self, retriever=None):
        self.retriever = retriever

    async def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs) -> None:
        if self.retriever is None:
            return

        # Only inject for analysis/report nodes
        tags = kwargs.get("tags", [])
        node_name = tags[0] if tags else ""
        if node_name not in ("analysis_expert", "report_generator"):
            return

        query = prompts[0] if prompts else ""
        if not query:
            return

        try:
            docs = await self.retriever.ainvoke(query)
            context = "\n".join([d.page_content[:300] for d in docs[:3]])
            if context:
                prompts[0] += f"\n\n## Reference Knowledge\n{context}"
                logger.debug(f"[RAGInjection] Injected {len(docs)} docs for {node_name}")
        except Exception as e:
            logger.warning(f"[RAGInjection] Failed: {e}")
