"""
经验复盘/整合/淘汰 Consolidator —— 书籍 Ch3 保存≠学习（离线整理阶段）。

【设计原则】
- 对应书籍 Ch3 的 User-as-Code 两阶段思想：
  第一阶段（在线）：经验以不可变日志形式追加保存（experience_store.save）
  第二阶段（离线）：周期性复盘，把碎片经验整合为结构化模型
- 整合动作均为确定性操作（SQL + Python），零 LLM，可安全批量执行
- 不删除原始经验，只做合并/标记，保证可回滚、可审计

【整合动作】
1. 去重合并（整合）：同一 fiber_key 下结论相似的碎片经验合并为一条，
   evidence 合并取并集
2. 补充溯源（整合）：为结论补充 evidence_source 便于溯源
3. 标记过期（淘汰）：长期未被更新的经验标记为 stale，供后续回收/下线

【执行方式】
  consolidate(store)  → 返回 ConsolidationReport
  由离线定时任务（如每日）调用，生产链路不阻塞在线推理。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..config import DATA_DIR

logger = logging.getLogger(__name__)

MEMORY_DB = str(DATA_DIR / "memory.db")

# 相似判定：结论去除标点后按长度分桶，同桶内视为"语义相近"候选
_SIMILAR_BUCKET_SIZE = 12  # 结论长度区间跨度

# 过期阈值：超过该天数未被更新的经验标记为 stale
STALE_DAYS = 180

# 最多保留同 fiber_key 的经验条数（超出的淘汰为 stale）
MAX_PER_FIBER = 20


@dataclass
class ConsolidationReport:
    """整合报告."""

    scanned: int = 0
    merged: int = 0
    merged_disks: int = 0
    hidden_duplicates: int = 0
    marked_stale: int = 0
    by_fiber: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "scanned": self.scanned,
            "merged": self.merged,
            "merged_disks": self.merged_disks,
            "hidden_duplicates": self.hidden_duplicates,
            "marked_stale": self.marked_stale,
            "by_fiber": self.by_fiber,
        }

    def __str__(self) -> str:
        return (
            f"Consolidation: scanned={self.scanned} merged={self.merged} "
            f"stale={self.marked_stale} duplicates_hidden={self.hidden_duplicates}"
        )


def _similarity_bucket(conclusion: str) -> int:
    """把结论映射为相似分桶键（去除标点后按长度分桶）。"""
    clean = "".join(ch for ch in conclusion if ch.isalnum())
    if not clean:
        return 0
    return len(clean) // _SIMILAR_BUCKET_SIZE


def _bigrams(text: str) -> set[str]:
    """字符二元组集合（用于相似度）。"""
    t = "".join(ch for ch in text if ch.isalnum())
    return {t[i : i + 2] for i in range(len(t) - 1)}


def _similarity(a: str, b: str) -> float:
    """二元组 Jaccard 相似度（0~1）。"""
    ga, gb = _bigrams(a), _bigrams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


# 相似结论合并阈值
MERGE_SIMILARITY = 0.45


class ExperienceConsolidator:
    """经验整合器（零 LLM，确定性 SQL 操作）。"""

    def __init__(self, db_path: str = MEMORY_DB):
        self._db_path = db_path

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        # 确保表存在（幂等）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fiber_key TEXT NOT NULL,
                severity TEXT NOT NULL,
                conclusion TEXT NOT NULL,
                evidence TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                stale INTEGER DEFAULT 0
            )
            """
        )
        # 兼容旧表：若缺 stale 列则补
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(analysis_experiences)")}
        if "stale" not in cols:
            conn.execute("ALTER TABLE analysis_experiences ADD COLUMN stale INTEGER DEFAULT 0")
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_exp_stale ON analysis_experiences(stale)")
        except sqlite3.OperationalError:
            pass
        return conn

    def consolidate(
        self,
        stale_days: int = STALE_DAYS,
        max_per_fiber: int = MAX_PER_FIBER,
        dry_run: bool = False,
    ) -> ConsolidationReport:
        """执行一次经验整合。

        【动作】
        1. 全量扫描经验
        2. 相似合并：同一 fiber_key 相似结论桶中，保留最新一条，其余合并 evidence
        3. 过期标记：created_at 距今超过 stale_days 标记 stale
        4. 超量淘汰：同 fiber_key 超过 max_per_fiber 的旧经验标记 stale
        """
        report = ConsolidationReport()
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM analysis_experiences WHERE stale = 0 " "ORDER BY fiber_key, id"
            ).fetchall()
            report.scanned = len(rows)

            # 按 fiber_key 分组
            by_fiber: dict[str, list[sqlite3.Row]] = {}
            for r in rows:
                by_fiber.setdefault(r["fiber_key"], []).append(r)

            for fiber_key, group in by_fiber.items():
                report.by_fiber[fiber_key] = len(group)
                self._consolidate_fiber(conn, fiber_key, group, report, stale_days, max_per_fiber, dry_run)

            if not dry_run:
                conn.commit()
            logger.info(str(report))
            return report
        finally:
            conn.close()

    def _consolidate_fiber(
        self,
        conn: sqlite3.Connection,
        fiber_key: str,
        group: list[sqlite3.Row],
        report: ConsolidationReport,
        stale_days: int,
        max_per_fiber: int,
        dry_run: bool,
    ) -> None:
        now = datetime.now()
        cutoff = (now - timedelta(days=stale_days)).isoformat()

        # 相似合并：按结论相似桶粗筛 → bigram Jaccard 精判，
        # 仅语义相近（>= MERGE_SIMILARITY）才合并，保留最新（id 最大）。
        # 先按 id 升序扫描，为每条"保留行"聚合其语义相近的后续碎片。
        keep_row: list[sqlite3.Row] = []  # 保留行的候选（各自收集可合并项）
        groups: list[list[sqlite3.Row]] = []  # 与 keep_row 一一对应
        for r in sorted(group, key=lambda x: x["id"]):
            target = _similarity_bucket(r["conclusion"])
            placed = False
            for k, cand in enumerate(keep_row):
                same_bucket = _similarity_bucket(cand["conclusion"]) == target
                if same_bucket and _similarity(cand["conclusion"], r["conclusion"]) >= MERGE_SIMILARITY:
                    # 找到语义相近的保留行，把 r 并入该组（不覆盖 cand）
                    groups[k].append(r)
                    placed = True
                    break
            if not placed:
                keep_row.append(r)
                groups.append([r])

        for k, cand in enumerate(keep_row):
            grp = groups[k]
            if len(grp) < 2:
                continue
            # 组内保留 id 最大者，其余合并 evidence（cand 是组内最早，但不一定是最大）
            keep = max(grp, key=lambda x: x["id"])
            to_merge = [x for x in grp if x["id"] != keep["id"]]
            combined_evidence = self._merge_evidence(keep, to_merge)
            if not dry_run:
                self._mark_merged(conn, keep["id"], combined_evidence, to_merge)
            report.merged += 1
            report.merged_disks += len(to_merge)

        # 过期标记
        old_rows = [r for r in group if r["created_at"] < cutoff]
        for r in old_rows:
            if not dry_run:
                self._mark_stale(conn, r["id"])
            report.marked_stale += 1

        # 超量淘汰（非 stale 的按 id 倒序保留 max_per_fiber 条）
        active = [r for r in group if r["created_at"] >= cutoff]
        if len(active) > max_per_fiber:
            remove = sorted(active, key=lambda r: r["id"])[: len(active) - max_per_fiber]
            for r in remove:
                if not dry_run:
                    self._mark_stale(conn, r["id"])
                report.marked_stale += 1

    @staticmethod
    def _merge_evidence(keep: sqlite3.Row, to_merge: list[sqlite3.Row]) -> str:
        """合并保留行与待合并行的 evidence 并集。"""
        import json

        combined: list[str] = []
        for raw in [keep["evidence"]] + [r["evidence"] for r in to_merge]:
            if not raw:
                continue
            try:
                items = json.loads(raw)
                if isinstance(items, list):
                    combined.extend(str(i) for i in items)
                else:
                    combined.append(str(items))
            except json.JSONDecodeError:
                combined.append(str(raw))
        # 去重保序
        seen: set[str] = set()
        unique: list[str] = []
        for item in combined:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return json.dumps(unique, ensure_ascii=False)

    @staticmethod
    def _mark_merged(conn: sqlite3.Connection, keep_id: int, evidence: str, merged_ids: list) -> None:
        conn.execute(
            "UPDATE analysis_experiences SET evidence = ? WHERE id = ?",
            (evidence, keep_id),
        )
        for r in merged_ids:
            conn.execute("DELETE FROM analysis_experiences WHERE id = ?", (r["id"],))

    @staticmethod
    def _mark_stale(conn: sqlite3.Connection, row_id: int) -> None:
        conn.execute("UPDATE analysis_experiences SET stale = 1 WHERE id = ?", (row_id,))


_consolidator: Any = None


def get_consolidator() -> ExperienceConsolidator:
    """进程级单例整合器."""
    global _consolidator
    if _consolidator is None:
        _consolidator = ExperienceConsolidator()
    return _consolidator
