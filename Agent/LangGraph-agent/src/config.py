"""
Fiber Maintenance Agent - Global Configuration.

v7.1-Final: Three-tier LLM gradient (14b/7b/3b) + Ollama Embedding.
All settings loaded from environment variables with sensible defaults.
Supports Windows (Agent) ↔ WSL (C++ Backend) communication.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


# =============================================================================
# Directory Paths
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", PROJECT_ROOT / "config"))
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Three-Tier LLM Configuration [v7.1]
# =============================================================================

@dataclass(frozen=True)
class LLMTierConfig:
    """Configuration for a single LLM tier."""

    model: str
    temperature: float
    timeout: int
    use_cases: tuple[str, ...]
    provider: str = "ollama"  # 每层可独立选择: ollama | openai


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# LLM Provider Mode: "ollama" (local) | "openai" (OpenAI-compatible API,
# e.g. Alibaba Cloud Bailian / DashScope compatible-mode)
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()

# OpenAI-compatible API endpoint & key (Bailian DashScope)
OPENAI_API_BASE = os.environ.get(
    "OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("DASHSCOPE_API_KEY", "")

LLM_CONFIG: dict[str, LLMTierConfig] = {
    "primary": LLMTierConfig(
        model=os.environ.get("LLM_PRIMARY", "qwen2.5:14b"),
        temperature=0.1,
        timeout=int(os.environ.get("LLM_PRIMARY_TIMEOUT", "60")),  # 14b 冷启动可达 30-60s
        use_cases=(
            "intent_classification",
            "analysis_expert",
            "report_generation",
            "report_evaluation",
        ),
        # 每层可单独指定 provider（默认继承全局 LLM_PROVIDER）
        provider=os.environ.get("LLM_PRIMARY_PROVIDER", LLM_PROVIDER),
    ),
    "secondary": LLMTierConfig(
        model=os.environ.get("LLM_SECONDARY", "qwen2.5:7b"),
        temperature=0.3,
        timeout=int(os.environ.get("LLM_SECONDARY_TIMEOUT", "45")),  # 7b 冷启动 ~15-45s
        use_cases=(
            "narrator",
            "knowledge_qa",
            "query_rewriter",
            "clarification",
        ),
        provider=os.environ.get("LLM_SECONDARY_PROVIDER", LLM_PROVIDER),
    ),
    "tertiary": LLMTierConfig(
        model=os.environ.get("LLM_TERTIARY", "qwen2.5:3b"),
        temperature=0.3,
        timeout=int(os.environ.get("LLM_TERTIARY_TIMEOUT", "30")),  # 3b 冷启动 ~10-30s
        use_cases=("emergency_fallback",),
        provider=os.environ.get("LLM_TERTIARY_PROVIDER", LLM_PROVIDER),
    ),
}


# =============================================================================
# Embedding Configuration [v7.1: Ollama-based]
# =============================================================================

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "bge-large")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))


# =============================================================================
# C++ Backend Connection (WSL)
# =============================================================================

FIBER_BACKEND_URL = os.environ.get("FIBER_BACKEND_URL", "http://localhost:8080")
WS_BACKEND_URL = os.environ.get("WS_BACKEND_URL", "ws://localhost:8081/ws/v1/events")


# =============================================================================
# ChromaDB (RAG Vector Store)
# =============================================================================

CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8100"))
CHROMA_PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", str(DATA_DIR / "chromadb"))


# =============================================================================
# Agent Server
# =============================================================================

AGENT_HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8000"))


# =============================================================================
# Domain Thresholds (Fiber Optic) — DEPRECATED: use src.governance.threshold_engine
# 保留向后兼容，新代码请使用 get_threshold_engine()
# =============================================================================

SPANLOSS_THRESHOLD = float(os.environ.get("SPANLOSS_THRESHOLD", "5.0"))  # DEPRECATED
SPANLOSS_CRITICAL = float(os.environ.get("SPANLOSS_CRITICAL", "8.0"))  # DEPRECATED
OOP_RANGE: tuple[float, float] = (-10.0, 3.0)  # 已同步 thresholds.yaml
IOP_RANGE: tuple[float, float] = (-25.0, -5.0)  # 已同步 thresholds.yaml


# =============================================================================
# Batch Limits
# =============================================================================

BATCH_MAX_TOTAL = int(os.environ.get("BATCH_MAX_TOTAL", "200"))
BATCH_CHUNK_SIZE = int(os.environ.get("BATCH_CHUNK_SIZE", "50"))
ALARM_BATCH_MAX = int(os.environ.get("ALARM_BATCH_MAX", "50"))


# =============================================================================
# Loop Control (Four Termination Safeguards)
# =============================================================================

MAX_LOOPS = int(os.environ.get("MAX_LOOPS", "3"))
MAX_LLM_CALLS = int(os.environ.get("MAX_LLM_CALLS", "10"))
MAX_NO_PROGRESS = int(os.environ.get("MAX_NO_PROGRESS", "2"))


# =============================================================================
# Circuit Breaker
# =============================================================================

CIRCUIT_BREAKER_THRESHOLD = int(os.environ.get("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_COOLDOWN = float(os.environ.get("CIRCUIT_BREAKER_COOLDOWN", "30"))


# =============================================================================
# Degradation
# =============================================================================

DEGRADATION_PROBE_INTERVAL = int(os.environ.get("DEGRADATION_PROBE_INTERVAL", "30"))


# =============================================================================
# Cache
# =============================================================================

LOCAL_CACHE_DB = os.environ.get("LOCAL_CACHE_DB", str(DATA_DIR / "local_cache.db"))
CACHE_DEFAULT_TTL = int(os.environ.get("CACHE_DEFAULT_TTL", "300"))  # 5 min


# =============================================================================
# Checkpointer
# =============================================================================

CHECKPOINT_DB = os.environ.get("CHECKPOINT_DB", str(DATA_DIR / "checkpoints.db"))

# Conversation sliding window [P0-B]: keep last N messages per thread.
# 10 turns ≈ 20 messages (Human + AI per turn). Bounds API token cost
# since primary LLM is billed per token (Bailian API).
MESSAGE_WINDOW_SIZE = int(os.environ.get("MESSAGE_WINDOW_SIZE", "20"))


# =============================================================================
# Audit
# =============================================================================

AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", str(DATA_DIR / "audit.jsonl"))
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "180"))


# =============================================================================
# Observability (Optional)
# =============================================================================

LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
PROMETHEUS_ENABLED = os.environ.get("PROMETHEUS_ENABLED", "true").lower() == "true"


# =============================================================================
# Security
# =============================================================================

MAX_INPUT_LENGTH = int(os.environ.get("MAX_INPUT_LENGTH", "2000"))
JWT_TOKEN = os.environ.get("JWT_TOKEN", "")
