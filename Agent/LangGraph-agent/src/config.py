"""
光纤维护 Agent - 全局配置。

【版本】v7.1-Final：三层 LLM 梯度（14b/7b/3b）+ Ollama Embedding。

【配置加载】
所有设置从环境变量加载，提供合理默认值。
支持 Windows（Agent）↔ WSL（C++ 后端）通信。

【面试知识点】
  Q: 为什么用三层 LLM？
  A: 不同任务复杂度不同：
     - 14b：复杂推理（意图分类、分析专家、报告生成）
     - 7b：中等任务（叙述员、知识问答）
     - 3b：紧急兆底（其他模型不可用时）
     分层可以优化成本和延迟。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 从项目根目录加载 .env
load_dotenv(Path(__file__).parent.parent / ".env")


# =============================================================================
# 目录路径
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data"))
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", PROJECT_ROOT / "config"))
KNOWLEDGE_BASE_DIR = PROJECT_ROOT / "knowledge_base"

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# 三层 LLM 配置 [v7.1]
# 【设计说明】每层可独立选择模型、温度、超时、甚至 provider
# =============================================================================


@dataclass(frozen=True)
class LLMTierConfig:
    """单个 LLM 层的配置。

    【字段说明】
    - model: 模型名称（如 qwen2.5:14b）
    - temperature: 生成温度（越低越确定性）
    - timeout: 请求超时（秒）
    - use_cases: 适用场景列表
    - provider: 每层可独立选择 provider（ollama/openai）
    """

    model: str
    temperature: float
    timeout: int
    use_cases: tuple[str, ...]
    provider: str = "ollama"  # 每层可独立选择: ollama | openai


OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# LLM Provider 模式："ollama"（本地）| "openai"（OpenAI 兼容 API，如阿里云百炼）
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()

# OpenAI 兼容 API 端点和密钥（百炼 DashScope）
OPENAI_API_BASE = os.environ.get("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
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
# Embedding 配置 [v7.1: 基于 Ollama]
# =============================================================================

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "bge-large")
EMBEDDING_DIMENSIONS = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))


# =============================================================================
# C++ 后端连接（WSL）
# =============================================================================

FIBER_BACKEND_URL = os.environ.get("FIBER_BACKEND_URL", "http://localhost:8080")
WS_BACKEND_URL = os.environ.get("WS_BACKEND_URL", "ws://localhost:8081/ws/v1/events")


# =============================================================================
# ChromaDB（RAG 向量存储）
# =============================================================================

CHROMADB_HOST = os.environ.get("CHROMADB_HOST", "localhost")
CHROMADB_PORT = int(os.environ.get("CHROMADB_PORT", "8100"))
CHROMA_PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", str(DATA_DIR / "chromadb"))


# =============================================================================
# Agent 服务器
# =============================================================================

AGENT_HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
AGENT_PORT = int(os.environ.get("AGENT_PORT", "8000"))


# =============================================================================
# 领域阈值（光纤）—— 已废弃：请使用 src.governance.threshold_engine
# 保留向后兼容，新代码请使用 get_threshold_engine()
# =============================================================================

SPANLOSS_THRESHOLD = float(os.environ.get("SPANLOSS_THRESHOLD", "5.0"))  # 已废弃
SPANLOSS_CRITICAL = float(os.environ.get("SPANLOSS_CRITICAL", "8.0"))  # 已废弃
OOP_RANGE: tuple[float, float] = (-10.0, 3.0)  # 已同步 thresholds.yaml
IOP_RANGE: tuple[float, float] = (-25.0, -5.0)  # 已同步 thresholds.yaml


# =============================================================================
# 批量限制
# =============================================================================

BATCH_MAX_TOTAL = int(os.environ.get("BATCH_MAX_TOTAL", "200"))
BATCH_CHUNK_SIZE = int(os.environ.get("BATCH_CHUNK_SIZE", "50"))
ALARM_BATCH_MAX = int(os.environ.get("ALARM_BATCH_MAX", "50"))


# =============================================================================
# 循环控制（四重终止保障）
# =============================================================================

MAX_LOOPS = int(os.environ.get("MAX_LOOPS", "3"))
MAX_LLM_CALLS = int(os.environ.get("MAX_LLM_CALLS", "10"))
MAX_NO_PROGRESS = int(os.environ.get("MAX_NO_PROGRESS", "2"))


# =============================================================================
# 熔断器
# =============================================================================

CIRCUIT_BREAKER_THRESHOLD = int(os.environ.get("CIRCUIT_BREAKER_THRESHOLD", "5"))
CIRCUIT_BREAKER_COOLDOWN = float(os.environ.get("CIRCUIT_BREAKER_COOLDOWN", "30"))


# =============================================================================
# 降级
# =============================================================================

DEGRADATION_PROBE_INTERVAL = int(os.environ.get("DEGRADATION_PROBE_INTERVAL", "30"))


# =============================================================================
# 缓存
# =============================================================================

LOCAL_CACHE_DB = os.environ.get("LOCAL_CACHE_DB", str(DATA_DIR / "local_cache.db"))
CACHE_DEFAULT_TTL = int(os.environ.get("CACHE_DEFAULT_TTL", "300"))  # 5 分钟


# =============================================================================
# 检查点器
# =============================================================================

CHECKPOINT_DB = os.environ.get("CHECKPOINT_DB", str(DATA_DIR / "checkpoints.db"))

# 用户记忆数据库 [P1]
USER_MEMORY_DB = os.environ.get("USER_MEMORY_DB", str(DATA_DIR / "user_memory.db"))

# 对话滑动窗口 [P0-B]：每个线程保留最近 N 条消息。
# 10 轮 ≈ 20 条消息（每轮 Human + AI）。控制 API token 成本。
MESSAGE_WINDOW_SIZE = int(os.environ.get("MESSAGE_WINDOW_SIZE", "20"))


# =============================================================================
# 审计
# =============================================================================

AUDIT_LOG_PATH = os.environ.get("AUDIT_LOG_PATH", str(DATA_DIR / "audit.jsonl"))
AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "180"))


# =============================================================================
# 可观测性（可选）
# =============================================================================

LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
PROMETHEUS_ENABLED = os.environ.get("PROMETHEUS_ENABLED", "true").lower() == "true"


# =============================================================================
# 安全
# =============================================================================

MAX_INPUT_LENGTH = int(os.environ.get("MAX_INPUT_LENGTH", "2000"))
JWT_TOKEN = os.environ.get("JWT_TOKEN", "")
