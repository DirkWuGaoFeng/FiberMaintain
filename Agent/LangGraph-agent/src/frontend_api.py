"""
Frontend API Router — v7.1 前端管理界面专属 API.

Endpoints:
  Knowledge:  GET/POST/DELETE /api/v1/knowledge/*
  Threads:    GET/DELETE      /api/v1/threads/*
  Graph:      GET             /api/v1/graph/structure
  Memory:     GET/POST        /api/v1/memory/*
  Confirm:    GET/POST        /api/v1/confirm/*   (写操作 HITL 门禁)
  Metrics:    GET             /api/v1/metrics/summary
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .config import (
    CHECKPOINT_DB,
    CHROMA_PERSIST_DIR,
    DATA_DIR,
    KNOWLEDGE_BASE_DIR,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 索引状态元数据文件
_INDEX_META_FILE = Path(CHROMA_PERSIST_DIR) / ".index_meta.json"

# 记忆存储 DB
MEMORY_DB = str(DATA_DIR / "memory.db")


# =============================================================================
# Knowledge Base APIs
# =============================================================================

@router.get("/api/v1/knowledge/docs")
async def list_knowledge_docs():
    """列出知识库文档（含分块数估算）."""
    kb_path = Path(KNOWLEDGE_BASE_DIR)
    documents = []

    if kb_path.exists():
        from .rag.engine import RAGEngine

        for filepath in sorted(kb_path.iterdir()):
            if filepath.is_file() and filepath.suffix in (".md", ".txt", ".pdf", ".rst"):
                try:
                    stat = filepath.stat()
                    content_len = stat.st_size
                    # 估算分块数: chunk_size=500, overlap=50
                    estimated_chunks = max(1, content_len // 450)
                    documents.append({
                        "name": filepath.name,
                        "category": RAGEngine._infer_category(filepath.name),
                        "chunkCount": estimated_chunks,
                        "sizeBytes": content_len,
                        "updatedAt": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    })
                except OSError as e:
                    logger.warning(f"[KnowledgeAPI] Failed to stat {filepath.name}: {e}")

    return {"documents": documents, "total": len(documents)}


@router.post("/api/v1/knowledge/upload")
async def upload_knowledge_doc(file: UploadFile = File(...)):
    """上传文档到知识库目录."""
    allowed_ext = {".md", ".txt", ".pdf", ".rst"}
    filename = file.filename or "unnamed.txt"
    ext = Path(filename).suffix.lower()

    if ext not in allowed_ext:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Allowed: {', '.join(allowed_ext)}",
        )

    # 安全检查：防止路径穿越
    safe_name = Path(filename).name
    kb_path = Path(KNOWLEDGE_BASE_DIR)
    kb_path.mkdir(parents=True, exist_ok=True)
    target = kb_path / safe_name

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:  # 20MB 上限
        raise HTTPException(status_code=400, detail="File too large (max 20MB)")

    target.write_bytes(content)

    # 估算分块数
    from .rag.engine import RAGEngine
    estimated_chunks = max(1, len(content) // 450)
    category = RAGEngine._infer_category(safe_name)

    logger.info(f"[KnowledgeAPI] Uploaded: {safe_name} ({len(content)} bytes)")
    return {"filename": safe_name, "chunks_added": estimated_chunks, "category": category}


@router.delete("/api/v1/knowledge/docs/{name}")
async def delete_knowledge_doc(name: str):
    """删除知识库文档."""
    safe_name = Path(name).name
    target = Path(KNOWLEDGE_BASE_DIR) / safe_name

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {safe_name}")

    target.unlink()
    logger.info(f"[KnowledgeAPI] Deleted: {safe_name}")
    return {"status": "ok"}


@router.post("/api/v1/knowledge/reindex")
async def reindex_knowledge():
    """全量重建向量索引."""
    import json

    try:
        from .rag.ingest import ingest_knowledge_base

        chunks = ingest_knowledge_base(
            kb_dir=str(KNOWLEDGE_BASE_DIR),
            persist_dir=str(CHROMA_PERSIST_DIR),
        )

        # 记录索引时间
        _INDEX_META_FILE.parent.mkdir(parents=True, exist_ok=True)
        _INDEX_META_FILE.write_text(
            json.dumps({"lastIndexedAt": datetime.now().isoformat(), "chunks": chunks}),
            encoding="utf-8",
        )

        # 重置 RAG 引擎单例，强制下次重新初始化
        from .rag import engine as engine_mod
        engine_mod._engine_instance = None

        logger.info(f"[KnowledgeAPI] Reindex complete: {chunks} chunks")
        return {"status": "ok", "chunks_ingested": chunks}
    except Exception as e:
        logger.error(f"[KnowledgeAPI] Reindex failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/api/v1/knowledge/search")
async def search_knowledge(req: SearchRequest):
    """检索测试 — 调用 RAG 混合检索引擎."""
    from .rag.engine import get_rag_engine

    engine = get_rag_engine()
    if engine is None:
        raise HTTPException(status_code=503, detail="RAG engine unavailable")

    results = await engine.retrieve(req.query, top_k=req.top_k)
    return {"results": results}


@router.get("/api/v1/knowledge/stats")
async def knowledge_stats():
    """索引统计信息."""
    import json

    kb_path = Path(KNOWLEDGE_BASE_DIR)
    docs = []
    category_dist: dict[str, int] = {}
    total_chunks = 0

    if kb_path.exists():
        from .rag.engine import RAGEngine

        for filepath in kb_path.iterdir():
            if filepath.is_file() and filepath.suffix in (".md", ".txt", ".pdf", ".rst"):
                docs.append(filepath)
                cat = RAGEngine._infer_category(filepath.name)
                category_dist[cat] = category_dist.get(cat, 0) + 1
                total_chunks += max(1, filepath.stat().st_size // 450)

    # 读取索引元数据
    last_indexed = None
    if _INDEX_META_FILE.exists():
        try:
            meta = json.loads(_INDEX_META_FILE.read_text(encoding="utf-8"))
            last_indexed = meta.get("lastIndexedAt")
        except Exception:
            pass

    # 引擎可用性
    from .rag.engine import get_rag_engine
    engine = get_rag_engine()
    engine_available = engine.is_available if engine else False

    return {
        "totalDocs": len(docs),
        "totalChunks": total_chunks,
        "categoryDistribution": category_dist,
        "lastIndexedAt": last_indexed,
        "engineAvailable": engine_available,
    }


# =============================================================================
# Thread Management APIs
# =============================================================================

@router.get("/api/v1/threads")
async def list_threads():
    """列出所有会话线程（从 checkpoint DB 读取）."""
    threads = []
    try:
        if os.path.exists(CHECKPOINT_DB):
            conn = sqlite3.connect(CHECKPOINT_DB)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT thread_id, MAX(checkpoint_id) as last_checkpoint
                FROM checkpoints
                GROUP BY thread_id
                ORDER BY last_checkpoint DESC
                LIMIT 50
            """)
            for row in cursor:
                threads.append({
                    "threadId": row["thread_id"],
                    "lastActiveAt": datetime.now().isoformat(),
                    "messageCount": None,
                    "preview": None,
                })
            conn.close()
    except Exception as e:
        logger.warning(f"[ThreadsAPI] Failed to read checkpoint DB: {e}")

    return {"threads": threads}


@router.get("/api/v1/threads/{thread_id}/state")
async def get_thread_state(thread_id: str):
    """获取线程状态快照（通过 LangGraph aget_state）."""
    try:
        from .graph.main_graph import get_graph

        graph = get_graph()
        state = await graph.aget_state({"configurable": {"thread_id": thread_id}})

        if state and state.values:
            values = state.values
            return {
                "threadId": thread_id,
                "currentNode": state.next[0] if state.next else None,
                "intent": values.get("intent"),
                "loopCount": values.get("loop_count", 0),
                "processingPath": values.get("processing_path", "normal"),
                "degradationLevel": values.get("degradation_level", 0),
                "finalOutput": values.get("final_output"),
            }

        return {
            "threadId": thread_id,
            "currentNode": None,
            "intent": None,
            "loopCount": 0,
            "processingPath": "normal",
            "degradationLevel": 0,
            "finalOutput": None,
        }
    except Exception as e:
        logger.warning(f"[ThreadsAPI] get_state failed for {thread_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/threads/{thread_id}")
async def delete_thread(thread_id: str):
    """删除线程（清理 checkpoint 记录）."""
    try:
        if os.path.exists(CHECKPOINT_DB):
            conn = sqlite3.connect(CHECKPOINT_DB)
            conn.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
            # 清理关联表（如果存在）
            for table in ("checkpoint_blobs", "checkpoint_writes"):
                try:
                    conn.execute(f"DELETE FROM {table} WHERE thread_id = ?", (thread_id,))
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            conn.close()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"[ThreadsAPI] Delete failed for {thread_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/threads/{thread_id}/interrupt")
async def interrupt_thread(thread_id: str):
    """中断线程当前执行（预留接口）."""
    # LangGraph 目前不支持远程中断正在运行的 invoke，
    # 此接口为前端提供语义化操作入口，实际中断由前端 AbortController 完成
    return {"status": "ok", "note": "interrupt signal acknowledged"}


# =============================================================================
# Graph Structure API
# =============================================================================

# 静态图结构定义（与 main_graph.py 完全一致）
_GRAPH_STRUCTURE = {
    "nodes": [
        {"id": "input_guard", "label": "输入防护", "type": "guard", "description": "输入长度/注入检测"},
        {"id": "rule_engine", "label": "规则引擎", "type": "router", "description": "快速路径匹配 (规则优先)"},
        {"id": "fast_path_executor", "label": "快速路径", "type": "executor", "description": "规则命中直接执行"},
        {"id": "intent_classifier", "label": "意图分类", "type": "router", "description": "LLM 9 类意图识别"},
        {"id": "param_gate", "label": "参数门控", "type": "guard", "description": "必要参数完整性校验"},
        {"id": "clarification", "label": "参数澄清", "type": "executor", "description": "向用户请求补充参数"},
        {"id": "intent_router", "label": "意图路由", "type": "router", "description": "按意图分发子图"},
        {
            "id": "data_collector", "label": "数据采集", "type": "subgraph",
            "description": "ReAct 工具调用子图 (15 工具)",
        },
        {"id": "batch_dispatcher", "label": "批量调度", "type": "executor", "description": "批量查询分片调度"},
        {"id": "knowledge_qa", "label": "知识问答", "type": "subgraph", "description": "RAG 知识检索子图"},
        {"id": "rule_judgment", "label": "规则判定", "type": "executor", "description": "阈值规则量化判定"},
        {"id": "analysis_expert", "label": "分析专家", "type": "executor", "description": "LLM 深度分析 + 循环决策"},
        {"id": "narrator", "label": "叙述生成", "type": "generator", "description": "LLM 结论叙述化"},
        {"id": "narrator_validator", "label": "叙述校验", "type": "validator", "description": "数据-结论一致性校验"},
        {"id": "template_fallback", "label": "模板兜底", "type": "generator", "description": "校验失败模板化输出"},
        {"id": "report_generator", "label": "报告生成", "type": "generator", "description": "结构化报告 LLM 生成"},
        {"id": "report_evaluator", "label": "报告评估", "type": "validator", "description": "报告质量评估 (≤1 次精化)"},
        {"id": "degradation_handler", "label": "降级处理", "type": "executor", "description": "五级降级链兜底输出"},
        {"id": "result_aggregator", "label": "结果聚合", "type": "aggregator", "description": "最终输出聚合 + 审计"},
    ],
    "edges": [
        {"source": "__start__", "target": "input_guard", "conditional": False},
        {"source": "input_guard", "target": "rule_engine", "conditional": False},
        {"source": "rule_engine", "target": "fast_path_executor", "label": "fast_path", "conditional": True},
        {"source": "rule_engine", "target": "param_gate", "label": "rule_hit_complex", "conditional": True},
        {"source": "rule_engine", "target": "intent_classifier", "label": "rule_miss", "conditional": True},
        {"source": "fast_path_executor", "target": "result_aggregator", "conditional": False},
        {"source": "intent_classifier", "target": "param_gate", "conditional": False},
        {"source": "param_gate", "target": "clarification", "label": "need_clarification", "conditional": True},
        {"source": "param_gate", "target": "intent_router", "label": "params_ok", "conditional": True},
        {"source": "clarification", "target": "rule_engine", "conditional": False, "isLoop": True},
        {"source": "intent_router", "target": "data_collector", "label": "data_query", "conditional": True},
        {"source": "intent_router", "target": "batch_dispatcher", "label": "batch_query", "conditional": True},
        {"source": "intent_router", "target": "knowledge_qa", "label": "knowledge_qa", "conditional": True},
        {"source": "intent_router", "target": "data_collector", "label": "report", "conditional": True},
        {"source": "intent_router", "target": "result_aggregator", "label": "chitchat", "conditional": True},
        {"source": "data_collector", "target": "rule_judgment", "conditional": False},
        {"source": "rule_judgment", "target": "analysis_expert", "conditional": False},
        {
            "source": "analysis_expert", "target": "data_collector", "label": "need_more_data",
            "conditional": True, "isLoop": True,
        },
        {"source": "analysis_expert", "target": "report_generator", "label": "generate_report", "conditional": True},
        {"source": "analysis_expert", "target": "narrator", "label": "direct_narrate", "conditional": True},
        {"source": "analysis_expert", "target": "degradation_handler", "label": "degraded", "conditional": True},
        {"source": "narrator", "target": "narrator_validator", "conditional": False},
        {"source": "narrator_validator", "target": "result_aggregator", "label": "pass", "conditional": True},
        {"source": "narrator_validator", "target": "template_fallback", "label": "fail", "conditional": True},
        {"source": "template_fallback", "target": "result_aggregator", "conditional": False},
        {"source": "report_generator", "target": "report_evaluator", "conditional": False},
        {"source": "report_evaluator", "target": "result_aggregator", "label": "pass", "conditional": True},
        {
            "source": "report_evaluator", "target": "report_generator", "label": "refine",
            "conditional": True, "isLoop": True,
        },
        {"source": "batch_dispatcher", "target": "result_aggregator", "conditional": False},
        {"source": "knowledge_qa", "target": "result_aggregator", "conditional": False},
        {"source": "degradation_handler", "target": "result_aggregator", "conditional": False},
        {"source": "result_aggregator", "target": "__end__", "conditional": False},
    ],
}


@router.get("/api/v1/graph/structure")
async def get_graph_structure():
    """返回主图静态结构（19 节点 + 32 边）."""
    return _GRAPH_STRUCTURE


# =============================================================================
# Memory APIs (SQLite 快照存储)
# =============================================================================

def _get_memory_conn() -> sqlite3.Connection:
    """获取记忆 DB 连接（自动建表）."""
    os.makedirs(os.path.dirname(MEMORY_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(MEMORY_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fiber_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fiber_id TEXT NOT NULL,
            spanloss REAL NOT NULL,
            color TEXT NOT NULL,
            summary TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_snapshots_fiber
        ON fiber_snapshots (fiber_id, created_at DESC)
    """)
    return conn


@router.get("/api/v1/memory/snapshots")
async def get_snapshots(
    fiber_id: str = Query(..., description="光纤 ID"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
):
    """查询光纤快照历史."""
    try:
        conn = _get_memory_conn()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = conn.execute(
            """
            SELECT fiber_id, spanloss, color, summary, created_at
            FROM fiber_snapshots
            WHERE fiber_id = ? AND created_at >= ?
            ORDER BY created_at DESC
            """,
            (fiber_id, cutoff),
        )
        snapshots = [dict(row) for row in cursor]
        conn.close()
        return {"snapshots": snapshots}
    except Exception as e:
        logger.error(f"[MemoryAPI] Query failed: {e}")
        return {"snapshots": []}


@router.get("/api/v1/memory/latest/{fiber_id}")
async def get_latest_snapshot(fiber_id: str):
    """获取光纤最新快照."""
    try:
        conn = _get_memory_conn()
        cursor = conn.execute(
            """
            SELECT fiber_id, spanloss, color, summary, created_at
            FROM fiber_snapshots
            WHERE fiber_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (fiber_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return {"snapshot": dict(row) if row else None}
    except Exception as e:
        logger.error(f"[MemoryAPI] Latest query failed: {e}")
        return {"snapshot": None}


class CleanupRequest(BaseModel):
    max_age_days: int = 90


@router.post("/api/v1/memory/cleanup")
async def cleanup_memory(req: CleanupRequest):
    """清理过期记忆快照."""
    try:
        conn = _get_memory_conn()
        cutoff = (datetime.now() - timedelta(days=req.max_age_days)).isoformat()
        cursor = conn.execute(
            "DELETE FROM fiber_snapshots WHERE created_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info(f"[MemoryAPI] Cleanup: {deleted} records older than {req.max_age_days} days")
        return {"deleted": deleted}
    except Exception as e:
        logger.error(f"[MemoryAPI] Cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Confirm APIs (写操作 HITL 确认门禁 [改进清单 P1-B])
# =============================================================================

@router.get("/api/v1/confirm/pending")
async def confirm_pending():
    """列出待用户确认的写操作（供确认卡片渲染）."""
    from .tools.confirmation_gate import get_confirmation_gate

    return {"pending": get_confirmation_gate().list_pending()}


@router.post("/api/v1/confirm/{token}")
async def confirm_execute(token: str):
    """确认并执行已登记的写操作.

    一次性消费 token，直接经 fiber_http_client 执行对应后端调用，
    不再经过工具层（避免二次进门禁）.
    """
    from .tools._http_client import fiber_http_client
    from .tools.confirmation_gate import get_confirmation_gate

    entry = get_confirmation_gate().confirm(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="确认令牌无效或已过期")

    operation = entry["operation"]
    params = entry["params"]
    try:
        if operation == "pull_call_create":
            result = await fiber_http_client.post(
                "/api/v1/pullcall/create", json=params, timeout=5.0
            )
        elif operation == "pull_call_cancel":
            req_params = {}
            if params.get("reason"):
                req_params["reason"] = params["reason"]
            result = await fiber_http_client.delete(
                f"/api/v1/pullcall/{params['session_id']}",
                timeout=3.0,
                params=req_params or None,
            )
        else:
            raise HTTPException(status_code=400, detail=f"未知写操作: {operation}")
        return {"status": "confirmed", "operation": operation, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ConfirmAPI] Execute {operation} failed: {e}")
        raise HTTPException(status_code=502, detail=f"写操作执行失败: {e}")


# =============================================================================
# Metrics Summary API
# =============================================================================

@router.get("/api/v1/metrics/summary")
async def metrics_summary():
    """结构化指标摘要（从 Prometheus REGISTRY 提取）."""
    summary = {
        "requestTotal": {},
        "ruleHitTotal": {},
        "toolCalls": {},
        "loopIterations": 0,
        "degradationLevel": 0,
        "tokenUsage": {},
        "narratorValidationFailures": 0,
        "requestDuration": {"avg": 0, "p95": 0, "count": 0},
    }

    try:
        from prometheus_client import REGISTRY

        for metric in REGISTRY.collect():
            # prometheus_client 对 Counter 会去除 _total 后缀作为 metric.name
            name = metric.name

            if name in ("fiber_agent_request_total", "fiber_agent_request"):
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        path = sample.labels.get("processing_path", "unknown")
                        summary["requestTotal"][path] = int(sample.value)

            elif name in ("fiber_agent_rule_hit_total", "fiber_agent_rule_hit"):
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        rule = sample.labels.get("rule_id", "unknown")
                        summary["ruleHitTotal"][rule] = int(sample.value)

            elif name in ("fiber_agent_tool_calls_total", "fiber_agent_tool_calls"):
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        tool = sample.labels.get("tool_name", "unknown")
                        status = sample.labels.get("status", "success")
                        if tool not in summary["toolCalls"]:
                            summary["toolCalls"][tool] = {"success": 0, "error": 0}
                        summary["toolCalls"][tool][status] = int(sample.value)

            elif name in ("fiber_agent_loop_iterations_total", "fiber_agent_loop_iterations"):
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        summary["loopIterations"] += int(sample.value)

            elif name in ("fiber_agent_token_usage_total", "fiber_agent_token_usage"):
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        tier = sample.labels.get("tier", "unknown")
                        summary["tokenUsage"][tier] = int(sample.value)

            elif name in ("fiber_agent_narrator_validation_failures_total", "fiber_agent_narrator_validation_failures"):
                for sample in metric.samples:
                    if sample.name.endswith("_total"):
                        summary["narratorValidationFailures"] += int(sample.value)

            elif name == "fiber_agent_request_duration_seconds":
                durations = []
                count = 0
                for sample in metric.samples:
                    if sample.name.endswith("_count"):
                        count = int(sample.value)
                    elif sample.name.endswith("_sum"):
                        durations.append(sample.value)
                if count > 0 and durations:
                    summary["requestDuration"]["avg"] = round(durations[0] / count * 1000, 1)
                    summary["requestDuration"]["count"] = count

    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"[MetricsAPI] Collection failed: {e}")

    # 附加降级等级
    try:
        from .resilience.degradation import get_degradation_manager
        dm = get_degradation_manager()
        if dm:
            status = dm.get_status()
            summary["degradationLevel"] = status.get("level", 0)
    except Exception:
        pass

    return summary

