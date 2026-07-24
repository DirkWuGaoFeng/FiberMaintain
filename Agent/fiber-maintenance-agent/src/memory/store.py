"""记忆系统：短期（50 条消息）+ 长期（分析结果持久化，对比分析）+ 知识库管理。
存储：SQLite（aiosqlite）。
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

import aiosqlite

from src.settings import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS analysis_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fiber_id INTEGER NOT NULL,
    analysis_type TEXT NOT NULL,
    result_json TEXT NOT NULL,
    summary TEXT,
    trace_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_fiber_time ON analysis_history(fiber_id, created_at);
CREATE INDEX IF NOT EXISTS idx_type_time ON analysis_history(analysis_type, created_at);

CREATE TABLE IF NOT EXISTS kb_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    category TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING/APPROVED/REJECTED/ACTIVE/DELETED
    review_comment TEXT,
    uploaded_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class MemoryStore:
    def __init__(self) -> None:
        self.db_path = settings.memory["db_path"]
        self.short_limit = settings.memory["short_term_limit"]
        self._inited = False

    async def _db(self) -> aiosqlite.Connection:
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        if not self._inited:
            await db.executescript(SCHEMA)
            await db.commit()
            self._inited = True
        return db

    # ─────────────── 短期记忆 ───────────────
    async def append_message(self, session_id: str, role: str,
                             content: str) -> None:
        db = await self._db()
        try:
            await db.execute(
                "INSERT INTO messages(session_id, role, content, created_at)"
                " VALUES (?,?,?,?)", (session_id, role, content, _now()))
            # 滑动窗口裁剪
            await db.execute("""
                DELETE FROM messages WHERE session_id=? AND id NOT IN (
                    SELECT id FROM messages WHERE session_id=?
                    ORDER BY id DESC LIMIT ?)""",
                (session_id, session_id, self.short_limit))
            await db.commit()
        finally:
            await db.close()

    async def get_recent(self, session_id: str) -> list[dict]:
        db = await self._db()
        try:
            cur = await db.execute(
                "SELECT role, content FROM messages WHERE session_id=?"
                " ORDER BY id DESC LIMIT ?", (session_id, self.short_limit))
            rows = await cur.fetchall()
            return [{"role": r["role"], "content": r["content"]}
                    for r in reversed(rows)]
        finally:
            await db.close()

    # ─────────────── 长期记忆（对比分析） ───────────────
    async def save_analysis(self, fiber_id: int, analysis_type: str,
                            result: dict, summary: str,
                            trace_id: str = "") -> int:
        db = await self._db()
        try:
            cur = await db.execute(
                "INSERT INTO analysis_history"
                "(fiber_id, analysis_type, result_json, summary, trace_id,"
                " created_at) VALUES (?,?,?,?,?,?)",
                (fiber_id, analysis_type,
                 json.dumps(result, ensure_ascii=False, default=str),
                 summary, trace_id, _now()))
            await db.commit()
            return cur.lastrowid
        finally:
            await db.close()

    async def query_analysis(self, fiber_id: int | None,
                             analysis_type: str | None,
                             start_time: str | None, end_time: str | None,
                             limit: int = 10) -> list[dict]:
        sql = "SELECT * FROM analysis_history WHERE 1=1"
        params: list = []
        if fiber_id is not None:
            sql += " AND fiber_id=?"; params.append(fiber_id)
        if analysis_type:
            sql += " AND analysis_type=?"; params.append(analysis_type)
        if start_time:
            sql += " AND created_at>=?"; params.append(start_time)
        if end_time:
            sql += " AND created_at<=?"; params.append(end_time)
        sql += " ORDER BY created_at DESC LIMIT ?"; params.append(limit)
        db = await self._db()
        try:
            cur = await db.execute(sql, params)
            rows = await cur.fetchall()
            return [{**dict(r), "result": json.loads(r["result_json"])}
                    for r in rows]
        finally:
            await db.close()

    # ─────────────── 知识库文档管理 ───────────────
    async def add_kb_doc(self, filename: str, file_path: str,
                         category: str, uploaded_by: str) -> int:
        db = await self._db()
        try:
            cur = await db.execute(
                "INSERT INTO kb_docs(filename, file_path, category, status,"
                " uploaded_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (filename, file_path, category, "PENDING", uploaded_by,
                 _now(), _now()))
            await db.commit()
            return cur.lastrowid
        finally:
            await db.close()

    async def list_kb_docs(self, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM kb_docs"
        params: list = []
        if status:
            sql += " WHERE status=?"; params.append(status)
        sql += " ORDER BY id DESC"
        db = await self._db()
        try:
            cur = await db.execute(sql, params)
            return [dict(r) for r in await cur.fetchall()]
        finally:
            await db.close()

    async def get_kb_doc(self, doc_id: int) -> dict | None:
        db = await self._db()
        try:
            cur = await db.execute("SELECT * FROM kb_docs WHERE id=?",
                                   (doc_id,))
            row = await cur.fetchone()
            return dict(row) if row else None
        finally:
            await db.close()

    async def update_kb_status(self, doc_id: int, status: str,
                               comment: str = "") -> None:
        db = await self._db()
        try:
            await db.execute(
                "UPDATE kb_docs SET status=?, review_comment=?, updated_at=?"
                " WHERE id=?", (status, comment, _now(), doc_id))
            await db.commit()
        finally:
            await db.close()


memory = MemoryStore()