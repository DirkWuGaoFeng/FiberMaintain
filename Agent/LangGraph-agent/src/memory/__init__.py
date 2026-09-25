"""
记忆包 — 长期存储与检索。

模块：
- experience_store: 基础经验存储（精确匹配）
- memory_retriever: 语义记忆检索（向量 + 模糊匹配）[P0-B]
- context_compressor: 对话上下文压缩 [P0-A]
- extractor: 会话后记忆提取器（书籍 Ch3 用户记忆核心机制）[P0-1]
"""

from .context_compressor import (
    ContextCompressor,
    ConversationSummary,
    get_context_compressor,
)
from .experience_store import ExperienceStore, get_experience_store
from .extractor import (
    MemoryCandidate,
    MemoryCandidateList,
    MemoryExtractor,
    get_memory_extractor,
)
from .memory_retriever import MemoryRetriever, get_memory_retriever
from .user_memory_retriever import (
    UserMemoryRetriever,
    get_user_memory_retriever,
)

__all__ = [
    "ExperienceStore",
    "get_experience_store",
    "MemoryRetriever",
    "get_memory_retriever",
    "ContextCompressor",
    "ConversationSummary",
    "get_context_compressor",
    "MemoryCandidate",
    "MemoryCandidateList",
    "MemoryExtractor",
    "get_memory_extractor",
    "UserMemoryRetriever",
    "get_user_memory_retriever",
]
