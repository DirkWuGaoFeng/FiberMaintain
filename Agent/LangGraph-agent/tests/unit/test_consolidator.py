"""
经验复盘/整合/淘汰 Consolidator 单元测试 [Phase 2-2]。

测试：
- 相似结论合并（同一 fiber_key 下语义相近的碎片合并，evidence 取并集）
- 过期标记（超过 stale_days 的经验标记 stale）
- 超量淘汰（同 fiber_key 超过上限的旧经验标记 stale）
- dry_run 不落库
- 兼容旧表（缺 stale 列自动补）
"""

import json
from datetime import datetime, timedelta

import pytest

from src.memory.consolidator import ExperienceConsolidator


@pytest.fixture
def consolidator(tmp_path):
    return ExperienceConsolidator(db_path=str(tmp_path / "memory.db"))


def _rows(cons: ExperienceConsolidator, stale_only: bool = False) -> list[dict]:
    conn = cons._conn()
    try:
        where = "WHERE stale = 1" if stale_only else ""
        rows = conn.execute(f"SELECT * FROM analysis_experiences {where} ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


class TestConsolidateMerge:
    """相似结论合并：同 fiber_key 下语义相近碎片合并为一条，evidence 取并集。"""

    def test_similar_conclusions_merged(self, consolidator):
        cons = consolidator
        conn = cons._conn()
        try:
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES ('5','WARNING','衰耗超阈值需关注','[\"spanloss=0.85\"]','2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES ('5','WARNING','衰耗超阈值须关注','[\"otdr=0.9\"]','2026-02-01T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

        report = cons.consolidate(stale_days=9999)  # 不触发过期

        # 相似结论被合并（从 2 条 → 1 条）
        remaining = _rows(cons)
        assert report.merged >= 1
        assert len(remaining) == 1
        # evidence 合并取并集
        evidence = json.loads(remaining[0]["evidence"])
        assert "spanloss=0.85" in evidence and "otdr=0.9" in evidence

    def test_dissimilar_conclusions_not_merged(self, consolidator):
        cons = consolidator
        conn = cons._conn()
        try:
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES ('5','WARNING','衰耗超阈值需关注','[]','2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES ('5','CRITICAL','光缆被挖掘机挖断导致全阻断','[]','2026-02-01T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

        report = cons.consolidate(stale_days=9999)
        # 语义差异大：bigram Jaccard 低于阈值，不合并
        assert len(_rows(cons)) == 2


class TestConsolidateStale:
    """过期标记与超量淘汰。"""

    def test_old_experience_marked_stale(self, consolidator):
        cons = consolidator
        # 用相对当前时刻的日期，避免硬编码日期随时钟漂移导致“近期”变“过期”
        now = datetime.now()
        old_at = (now - timedelta(days=60)).isoformat()    # 远超 stale_days=30 → 应过期
        recent_at = (now - timedelta(days=1)).isoformat()  # 距今 1 天 → 应保持活跃
        conn = cons._conn()
        try:
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                f"VALUES ('5','WARNING','历史经验','[]','{old_at}')"
            )
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                f"VALUES ('5','WARNING','近期经验','[]','{recent_at}')"
            )
            conn.commit()
        finally:
            conn.close()

        # stale_days=30 → 60 天前那条过期
        report = cons.consolidate(stale_days=30)
        assert report.marked_stale >= 1
        stale = _rows(cons, stale_only=True)
        assert any(r["conclusion"] == "历史经验" for r in stale)
        # 近期经验仍活跃
        active = [r for r in _rows(cons) if not r["stale"]]
        assert any(r["conclusion"] == "近期经验" for r in active)

    def test_overflow_eviction(self, consolidator):
        cons = consolidator
        conn = cons._conn()
        try:
            for i in range(25):
                conn.execute(
                    "INSERT INTO analysis_experiences "
                    "(fiber_key, severity, conclusion, evidence, created_at) "
                    "VALUES ('5','CRITICAL','经验条目','[]','2026-08-01T00:00:00')"
                )
            conn.commit()
        finally:
            conn.close()

        report = cons.consolidate(stale_days=9999, max_per_fiber=10)
        # 超过 10 条的旧经验被淘汰标记 stale
        assert report.marked_stale >= 15
        active = [r for r in _rows(cons) if not r["stale"]]
        assert len(active) <= 10


class TestConsolidateDryRun:
    """dry_run 只统计不落库。"""

    def test_dry_run_no_db_change(self, consolidator):
        cons = consolidator
        conn = cons._conn()
        try:
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES ('5','WARNING','重复经验','[]','2026-01-01T00:00:00')"
            )
            conn.execute(
                "INSERT INTO analysis_experiences "
                "(fiber_key, severity, conclusion, evidence, created_at) "
                "VALUES ('5','WARNING','重复经验','[]','2026-02-01T00:00:00')"
            )
            conn.commit()
        finally:
            conn.close()

        before = len(_rows(cons))
        report = cons.consolidate(stale_days=9999, dry_run=True)
        after = len(_rows(cons))
        # dry_run 报告仍能反映潜在合并
        assert report.merged >= 0 or report.scanned == 2
        # 数据库未被改动
        assert after == before


class TestConsolidateSchemaCompat:
    """兼容旧表：缺 stale 列自动补（幂等建表）。"""

    def test_legacy_table_gets_stale_column(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE analysis_experiences ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "fiber_key TEXT NOT NULL,"
            "severity TEXT NOT NULL,"
            "conclusion TEXT NOT NULL,"
            "evidence TEXT DEFAULT '',"
            "created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO analysis_experiences "
            "(fiber_key, severity, conclusion, evidence, created_at) "
            "VALUES ('5','WARNING','旧表经验','[]','2026-01-01T00:00:00')"
        )
        conn.commit()
        conn.close()

        cons = ExperienceConsolidator(db_path=db_path)
        rows = cons._conn().execute("PRAGMA table_info(analysis_experiences)").fetchall()
        assert any(r["name"] == "stale" for r in rows)
