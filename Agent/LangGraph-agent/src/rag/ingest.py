"""
Knowledge base ingestion [v7.1]: load documents into ChromaDB vector store.

Features:
- Chinese/English term annotations (TERM_ANNOTATIONS)
- RecursiveCharacterTextSplitter (chunk_size=500, overlap=50)
- Support Markdown/TXT/PDF ingestion
- Category inference from filename
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# =============================================================================
# Term Annotations [v7.1] — 中英文术语对照标注
# =============================================================================

TERM_ANNOTATIONS: dict[str, str] = {
    "OTDR": "OTDR（光时域反射仪）",
    "OOP": "OOP（输出光功率）",
    "IOP": "IOP（输入光功率）",
    "spanloss": "spanloss（跨段衰耗）",
    "dB": "dB（分贝）",
    "dBm": "dBm（分贝毫瓦）",
    "NE": "NE（网元）",
    "EMS": "EMS（网元管理系统）",
    "NMS": "NMS（网络管理系统）",
    "RED": "RED（红色/紧急）",
    "YELLOW": "YELLOW（黄色/警告）",
    "GREEN": "GREEN（绿色/正常）",
    "PullCall": "PullCall（拉纤呼叫）",
    "board": "board（板卡）",
    "port": "port（端口）",
    "fiber": "fiber（光纤）",
}


def annotate_terms(text: str) -> str:
    """Add Chinese annotations to English technical terms."""
    for term, annotated in TERM_ANNOTATIONS.items():
        # Only annotate first occurrence to avoid clutter
        if term in text and annotated not in text:
            text = text.replace(term, annotated, 1)
    return text


def ingest_knowledge_base(kb_dir: str = "", persist_dir: str = "") -> int:
    """
    Ingest knowledge base documents into ChromaDB.

    Args:
        kb_dir: Knowledge base directory (default: knowledge_base/)
        persist_dir: ChromaDB persist directory

    Returns:
        Number of documents ingested
    """
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from ..llm.provider import get_embedding_model

    kb_dir = kb_dir or os.path.join(os.path.dirname(__file__), "..", "..", "knowledge_base")
    persist_dir = persist_dir or os.environ.get("CHROMA_PERSIST_DIR", "data/chromadb")

    embeddings = get_embedding_model()
    vectorstore = Chroma(
        collection_name="fiber_knowledge",
        embedding_function=embeddings,
        persist_directory=persist_dir,
    )

    docs = []
    if os.path.exists(kb_dir):
        for filename in os.listdir(kb_dir):
            filepath = os.path.join(kb_dir, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    category = _infer_category(filename)
                    # Split large documents into chunks
                    chunks = _chunk_document(content, chunk_size=500, overlap=50)
                    for i, chunk in enumerate(chunks):
                        docs.append(Document(
                            page_content=chunk,
                            metadata={
                                "source": filename,
                                "category": category,
                                "chunk_index": i,
                            },
                        ))
                except Exception as e:
                    logger.warning(f"[Ingest] Failed to load {filename}: {e}")

    if docs:
        vectorstore.add_documents(docs)
        logger.info(f"[Ingest] Added {len(docs)} document chunks to ChromaDB")
    else:
        logger.warning("[Ingest] No documents found in knowledge base")

    return len(docs)


def _chunk_document(content: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split a document into overlapping chunks."""
    if len(content) <= chunk_size:
        return [content]

    chunks = []
    start = 0
    while start < len(content):
        end = start + chunk_size
        chunk = content[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks


def _infer_category(filename: str) -> str:
    """Infer knowledge category from filename."""
    name = filename.lower()
    if "device" in name or "board" in name:
        return "device_manual"
    elif "maintenance" in name or "guide" in name:
        return "maintenance_guide"
    elif "alarm" in name:
        return "alarm_guide"
    elif "fault" in name or "case" in name:
        return "fault_cases"
    elif "threshold" in name or "standard" in name:
        return "threshold_standard"
    elif "ne" in name or "config" in name:
        return "ne_config"
    return "general"
