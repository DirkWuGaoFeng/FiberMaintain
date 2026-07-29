"""
Phase 4.3: Prompt 版本管理

- 语义化版本号 + SHA256 哈希
- 模板变量注入 ({{prompt_version}}, {{temperature}} 等)
- A/B 测试预留 (10% 流量)
- prompt_audit_log 表 (SQLite)
"""
from __future__ import annotations
import hashlib
import json
import logging
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("fiber.prompt")


# ============================================================
#  PromptVersion — 版本元数据
# ============================================================

@dataclass
class PromptVersion:
    """Prompt 版本记录。"""
    name: str                        # prompt 名称 (e.g. "lead_system")
    version: str                     # 语义化版本 (e.g. "1.2.0")
    content: str                     # prompt 模板内容
    sha256: str = ""                 # 内容哈希
    variables: dict = field(default_factory=dict)  # 默认模板变量
    created_at: str = ""
    is_active: bool = True

    def __post_init__(self):
        if not self.sha256:
            self.sha256 = hashlib.sha256(
                self.content.encode("utf-8")).hexdigest()[:16]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def render(self, **kwargs) -> str:
        """渲染模板变量。"""
        merged = {**self.variables, **kwargs}
        result = self.content
        for key, val in merged.items():
            result = result.replace("{{" + key + "}}", str(val))
        return result


# ============================================================
#  ABTestConfig — A/B 测试配置
# ============================================================

@dataclass
class ABTestConfig:
    """A/B 测试：10% 流量走 B 版本。"""
    enabled: bool = False
    variant_name: str = ""           # B 版本 prompt 名称
    variant_version: str = ""        # B 版本号
    traffic_ratio: float = 0.10      # 10% 流量

    def should_use_variant(self) -> bool:
        if not self.enabled or not self.variant_name:
            return False
        return random.random() < self.traffic_ratio


# ============================================================
#  PromptRegistry — 版本注册表
# ============================================================

class PromptRegistry:
    """Prompt 版本注册表：内存存储 + SQLite 审计日志。"""

    def __init__(self, db_path: str = "logs/prompt_audit.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = db_path
        self._prompts: dict[str, dict[str, PromptVersion]] = {}  # name → {version → PromptVersion}
        self._active: dict[str, str] = {}   # name → active_version
        self._ab_tests: dict[str, ABTestConfig] = {}
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    metadata TEXT DEFAULT '{}'
                )
            """)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db)

    def _audit(self, action: str, prompt: PromptVersion,
               metadata: dict | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO prompt_audit_log"
                "(name, version, sha256, action, metadata)"
                " VALUES (?,?,?,?,?)",
                (prompt.name, prompt.version, prompt.sha256,
                 action, json.dumps(metadata or {}, default=str)))

    def register(self, prompt: PromptVersion) -> None:
        """注册一个 prompt 版本。"""
        if prompt.name not in self._prompts:
            self._prompts[prompt.name] = {}
        self._prompts[prompt.name][prompt.version] = prompt
        if prompt.is_active or prompt.name not in self._active:
            self._active[prompt.name] = prompt.version
        self._audit("register", prompt)
        logger.info("Prompt registered: %s v%s (%s)",
                     prompt.name, prompt.version, prompt.sha256)

    def get(self, name: str, version: str | None = None) -> PromptVersion | None:
        """获取指定版本或活跃版本的 prompt。"""
        versions = self._prompts.get(name, {})
        if not versions:
            return None

        # A/B 测试检查
        ab = self._ab_tests.get(name)
        if ab and ab.should_use_variant():
            variant = self._prompts.get(ab.variant_name, {}).get(ab.variant_version)
            if variant:
                logger.info("A/B test: using variant %s v%s for %s",
                            ab.variant_name, ab.variant_version, name)
                return variant

        ver = version or self._active.get(name)
        return versions.get(ver)

    def get_active(self, name: str) -> PromptVersion | None:
        return self.get(name)

    def set_active(self, name: str, version: str) -> bool:
        """设置活跃版本。"""
        if name in self._prompts and version in self._prompts[name]:
            self._active[name] = version
            prompt = self._prompts[name][version]
            self._audit("set_active", prompt)
            logger.info("Prompt active: %s → v%s", name, version)
            return True
        return False

    def configure_ab(self, name: str, config: ABTestConfig) -> None:
        self._ab_tests[name] = config
        logger.info("A/B test configured: %s → %s (%.0f%%)",
                     name, config.variant_name, config.traffic_ratio * 100)

    def list_versions(self, name: str) -> list[str]:
        return list(self._prompts.get(name, {}).keys())

    def render(self, name: str, **kwargs) -> str | None:
        """获取并渲染 prompt。"""
        prompt = self.get(name)
        if prompt is None:
            return None
        return prompt.render(**kwargs)


# ============================================================
#  Default Prompts — 内置 prompt 注册
# ============================================================

def register_defaults(registry: PromptRegistry) -> None:
    """注册所有默认 prompt 版本。"""

    # Lead Agent System Prompt
    registry.register(PromptVersion(
        name="lead_system",
        version="3.2.1",
        content="""你是光纤维护智能助手 FiberBot v{{prompt_version}}，
负责协调 Sub-Agent 完成光纤维护分析任务。

## 可用 Sub-Agent
- data-collector: 数据采集（支持批量查询，上限200条）
- analysis-expert: 数据分析专家（温度={{temperature}}）
- knowledge-assistant: 知识检索助手（RAG + 向量搜索）
- report-generator: 报告生成器

## 工作规范
1. 先理解用户需求，制定分析计划
2. 按需调度 Sub-Agent 获取数据和分析
3. 综合分析结果，给出专业建议
4. 必要时生成结构化报告""",
        variables={"prompt_version": "3.2.1", "temperature": "0.3"},
    ))

    # Data Collector Prompt
    registry.register(PromptVersion(
        name="data_collector_system",
        version="3.2.1",
        content="""你是数据采集专家，负责从后端系统获取光纤维护数据。

## 可用工具
- fiber_performance_query: 单纤性能查询
- fiber_spanloss_query: 单纤衰耗查询
- fiber_connection_query: 连纤拓扑查询
- batch_fiber_performance_query: 批量性能查询（上限200）
- batch_fiber_spanloss_query: 批量衰耗查询（上限200）
- fiber_trend_query: 趋势数据查询

## 规范
- 严格按照请求的参数查询，不自行编造数据
- 批量查询自动分片（chunk=50）
- 返回原始数据，不做分析解读""",
        variables={"prompt_version": "3.2.1", "temperature": "0.0"},
    ))

    # Analysis Expert Prompt
    registry.register(PromptVersion(
        name="analysis_expert_system",
        version="3.2.1",
        content="""你是光纤维护分析专家，基于采集数据进行专业分析。

## 分析框架
1. 数据完整性检查
2. 阈值对比分析（参考知识库标准）
3. 趋势研判（如有历史数据）
4. 风险评估与建议

## 颜色阈值标准
- 绿色(正常): 衰耗 0~5 dB
- 黄色(告警): 衰耗 5~10 dB
- 橙色(严重): 衰耗 10~15 dB
- 红色(紧急): 衰耗 >15 dB""",
        variables={"prompt_version": "3.2.1", "temperature": "0.1"},
    ))

    logger.info("Default prompts registered: %d prompts",
                len(registry._prompts))


# ============================================================
#  PromptManager — 全局管理器
# ============================================================

class PromptManager:
    """Prompt 管理器：全局单例。"""

    _instance: PromptManager | None = None

    def __init__(self, db_path: str = "logs/prompt_audit.db"):
        self.registry = PromptRegistry(db_path)
        register_defaults(self.registry)

    @classmethod
    def get_instance(cls, db_path: str = "logs/prompt_audit.db") -> PromptManager:
        if cls._instance is None:
            cls._instance = cls(db_path)
        return cls._instance

    def render(self, name: str, **kwargs) -> str | None:
        return self.registry.render(name, **kwargs)

    def get(self, name: str, version: str | None = None) -> PromptVersion | None:
        return self.registry.get(name, version)
