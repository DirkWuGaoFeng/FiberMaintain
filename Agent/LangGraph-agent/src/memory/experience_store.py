"""
经验存储 —— 故障处理经验记忆 [改进清单 P1-A]。

SQLite 表 `analysis_experiences` 与 fiber_snapshots 位于同一个
memory.db 中（frontend_api.MEMORY_DB）。设计约束：

- 仅确定性写入：当严重程度为 WARNING/CRITICAL 时，由 analysis_expert
  持久化经验 —— 绝不通过 LLM 自行调用工具写入，以免在
  "规则优先、LLM 兜底"的系统中引入记忆噪声。
- 类颜色变化的去重：当同一光纤的最新经验已是相同严重程度时跳过，
  避免重复告警刷屏数据表。
- 检索结果注入到分析提示词中，而非由 LLM 自行决定。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..config import DATA_DIR
from ..governance.report_checklist import check_numbers_grounded

logger = logging.getLogger(__name__)

MEMORY_DB = str(DATA_DIR / "memory.db")
MAX_EVIDENCE_CHARS = 1000
MAX_SUMMARY_CHARS = 300


class ExperienceStore:
    """SQLite-backed store for analysis experiences."""

    def __init__(self, db_path: str = MEMORY_DB):
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiber_key TEXT NOT NULL,
                severity TEXT NOT NULL,
                conclusion TEXT NOT NULL,
                evidence TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_fiber ON analysis_experiences(fiber_key)")
        return conn

    @staticmethod
    def fiber_key_of(fiber_ids: list | None) -> str:
        """Normalize fiber_ids to a stable key ('' when absent)."""
        if not fiber_ids:
            return ""
        return ",".join(str(f) for f in fiber_ids[:5])

    @staticmethod
    def _passes_quality_veto(conclusion: str, evidence: list | None) -> bool:
        """经验质量门禁（书籍 Ch3：保存≠学习）。

        结论中的数字必须能溯源到自身 evidence（不出现幻觉数字），
        否则拒绝写入，防止坏经验污染后续判断。
        【保守性】结论无数字 → 放行（不误伤纯文字结论）。
        """
        if not conclusion:
            return False
        result = check_numbers_grounded(conclusion, [str(e) for e in (evidence or [])])
        return bool(result.get("passed", False))

    def save(
        self,
        fiber_key: str,
        severity: str,
        conclusion: str,
        evidence: list | None = None,
    ) -> bool:
        """Persist one experience. Returns False when dedup skips it."""
        if not fiber_key or severity not in ("WARNING", "CRITICAL"):
            return False
        # 质量门禁：坏经验（结论数字无法溯源）不入库
        if not self._passes_quality_veto(conclusion, evidence):
            logger.info(f"[Experience] Quality veto: {fiber_key} 结论含无法溯源的数字，拒绝写入")
            return False
        conn = self._conn()
        try:
            latest = self._latest(conn, fiber_key)
            if latest and latest["severity"] == severity:
                logger.debug(f"[Experience] Dedup skip: {fiber_key} already {severity}")
                return False
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    fiber_key,
                    severity,
                    conclusion[:MAX_SUMMARY_CHARS],
                    json.dumps(evidence or [], ensure_ascii=False)[:MAX_EVIDENCE_CHARS],
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            logger.info(f"[Experience] Saved {severity} experience for {fiber_key}")
            return True
        finally:
            conn.close()

    def query(self, fiber_key: str, days: int = 90, limit: int = 5) -> list[dict]:
        """Recent experiences for the fiber key (newest first)."""
        if not fiber_key:
            return []
        conn = self._conn()
        try:
            since = (datetime.now() - timedelta(days=days)).isoformat()
            rows = conn.execute(
                "SELECT severity, conclusion, evidence, created_at "
                "FROM analysis_experiences "
                "WHERE fiber_key = ? AND created_at >= ? "
                "ORDER BY created_at DESC LIMIT ?",
                (fiber_key, since, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def latest_severity(self, fiber_key: str) -> Optional[str]:
        """获取最新经验的严重程度，若无则返回 None。"""
        if not fiber_key:
            return None
        conn = self._conn()
        try:
            latest = self._latest(conn, fiber_key)
            return latest["severity"] if latest else None
        finally:
            conn.close()

    @staticmethod
    def _latest(conn: sqlite3.Connection, fiber_key: str) -> Optional[sqlite3.Row]:
        return conn.execute(
            "SELECT severity FROM analysis_experiences " "WHERE fiber_key = ? ORDER BY id DESC LIMIT 1",
            (fiber_key,),
        ).fetchone()


_store: Optional[ExperienceStore] = None


def get_experience_store() -> ExperienceStore:
    """进程级单例经验存储。"""
    global _store
    if _store is None:
        _store = ExperienceStore()
    return _store
