"""FastAPI 入口：对话(SSE) / 报告下载 / 知识库管理 / 插件 / 监控 / 健康检查。"""
from __future__ import annotations
import asyncio, json, logging, shutil, time, uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
import websockets
from prometheus_client import make_asgi_app

from src.settings import settings
from src.agents.lead_agent import orchestrator
from src.mcp import backend
from src.mcp.fiber_backend import BackendUnavailable
from src.memory.store import memory
from src.export.exporters import resolve_file, cleanup_expired, REPORT_DIR
from src.notify.notifier import notifier
from src.plugins.sdk import (discover_plugins, reload_plugins, list_plugins,
                             plugin_watch_loop)
from src.rag.engine import rag_engine
from src.rag.ingest import ingest_file, DIR_COLLECTION
from src.monitoring.metrics import BACKEND_UP
from src.monitoring.observability import get_observability

# ── 日志配置（显式挂载到 fiber 命名空间，兼容 uvicorn 已配置 root logger 的场景） ──
_LOG_FMT = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
_fiber_logger = logging.getLogger("fiber")
_fiber_logger.setLevel(logging.INFO)
_fiber_logger.propagate = False
if not _fiber_logger.handlers:
    _sh = logging.StreamHandler()
    _sh.setFormatter(_LOG_FMT)
    _fiber_logger.addHandler(_sh)
    _fh = logging.FileHandler(f"{settings.app['log_dir']}/app.log",
                              encoding="utf-8")
    _fh.setFormatter(_LOG_FMT)
    _fiber_logger.addHandler(_fh)
logger = logging.getLogger("fiber.main")


def _flush_logs() -> None:
    """强制 flush 所有 fiber logger 的 handler，确保日志立即落盘。"""
    for h in logging.getLogger("fiber").handlers:
        h.flush()


# ───────────────────────── 后台任务 ─────────────────────────
async def backend_watchdog() -> None:
    """每 10s 探测后端；连续不可用 > 60s → 严重通知。"""
    notified = False
    while True:
        await asyncio.sleep(10)
        ok = await backend.health()
        BACKEND_UP.set(1 if ok else 0)
        if not ok and backend.down_since and not notified:
            down_for = asyncio.get_running_loop().time()
            import time
            if time.time() - backend.down_since > \
                    settings.backend["down_threshold_seconds"]:
                await notifier.send_critical(
                    "后端服务不可用",
                    f"API Gateway ({settings.backend['base_url']}) 连续不可用超过 "
                    f"{settings.backend['down_threshold_seconds']}s，"
                    f"Agent 已进入离线模式（仅 RAG 问答）。")
                notified = True
        elif ok:
            notified = False

async def report_cleaner() -> None:
    while True:
        await asyncio.sleep(3600)
        n = await asyncio.to_thread(cleanup_expired)
        if n:
            logger.info("清理过期报告 %d 个", n)

@asynccontextmanager
async def lifespan(app: FastAPI):
    discover_plugins()
    notifier.start()
    tasks = [
        asyncio.create_task(backend_watchdog()),
        asyncio.create_task(report_cleaner()),
        asyncio.create_task(plugin_watch_loop()),
    ]
    logger.info("光纤维护 Agent 启动 (v%s)", settings.app["version"])
    yield
    for t in tasks:
        t.cancel()
    await notifier.stop()
    await backend.close()


app = FastAPI(title="光纤维护服务系统 Agent",
              version=settings.app["version"], lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.mount("/metrics", make_asgi_app())


# ───────────────────────── 对话（SSE 流式） ─────────────────────────
@app.post("/api/v1/chat")
async def chat(req: Request):
    body = await req.json()
    session_id = body.get("session_id") or f"s-{uuid.uuid4().hex[:8]}"
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(400, "message 不能为空")

    logger.info("[Chat] 收到请求 session_id=%s message_len=%d message=%.80s",
                session_id, len(message), message[:80])
    _flush_logs()

    obs = get_observability(settings.app["log_dir"])

    async def event_stream():
        trace_id = obs.start_trace("chat")
        t0 = time.perf_counter()
        obs.metrics.inc("chat_request")
        # 手动创建 span（避免 with 在 async generator 中过早退出）
        span = obs.span("orchestrator.run", attributes={"session_id": session_id, "message_len": len(message)})
        span.__enter__()
        event_count = 0
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        try:
            async for ev in orchestrator.run(session_id, message):
                event_count += 1
                ev_type = ev.get("type", "unknown")
                # 记录关键事件
                if ev_type == "token":
                    logger.debug("[Chat][%s] token len=%d", session_id, len(ev.get("content", "")))
                elif ev_type == "tool_call":
                    logger.info("[Chat][%s] tool_call tool=%s", session_id, ev.get("tool"))
                elif ev_type == "tool_result":
                    logger.info("[Chat][%s] tool_result tool=%s content_len=%d",
                                session_id, ev.get("tool"), len(ev.get("content", "")))
                elif ev_type == "subagent":
                    logger.info("[Chat][%s] subagent agent=%s", session_id, ev.get("agent"))
                elif ev_type == "thought":
                    logger.info("[Chat][%s] thought: %.100s", session_id, ev.get("content", "")[:100])
                elif ev_type == "warning":
                    logger.warning("[Chat][%s] warning: %.100s", session_id, ev.get("content", "")[:100])
                elif ev_type == "error":
                    logger.error("[Chat][%s] error: %.200s", session_id, ev.get("content", "")[:200])
                elif ev_type == "done":
                    logger.info("[Chat][%s] done elapsed_ms=%s", session_id, ev.get("elapsed_ms"))
                # 捕获 sub-agent 调用事件，记录指标
                if ev_type == "subagent":
                    agent_name = ev.get("agent", "unknown")
                    obs.metrics.inc(f"subagent_{agent_name}")
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            obs.end_trace(trace_id, "ok")
            obs.metrics.inc("trace_ok")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.info("[Chat] 完成 session_id=%s events=%d elapsed=%.0fms",
                        session_id, event_count, elapsed_ms)
            _flush_logs()
        except Exception as e:
            obs.end_trace(trace_id, "error")
            obs.metrics.inc("trace_error")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            logger.error("[Chat] 异常 session_id=%s elapsed=%.0fms error=%s",
                         session_id, elapsed_ms, e, exc_info=True)
            raise
        finally:
            span.__exit__(None, None, None)  # 记录 span
            obs.record_latency("chat_latency", (time.perf_counter() - t0) * 1000)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(),
                             media_type="text/event-stream",
                             headers={"X-Accel-Buffering": "no"})


@app.get("/api/v1/sessions/{session_id}/history")
async def history(session_id: str):
    return {"messages": await memory.get_recent(session_id)}


# ───────────────────────── 报告下载 ─────────────────────────
@app.get("/api/v1/reports/download/{file_id}")
async def download_report(file_id: str):
    path = resolve_file(file_id)
    if not path:
        raise HTTPException(404, "文件不存在或已过期（24h）")
    return FileResponse(path, filename=path.name)


# ───────────────────────── 知识库管理（§12） ─────────────────────────
def _check_role(request: Request, required: str = "admin") -> str:
    role = request.headers.get("X-User-Role", "operator")
    if required == "admin" and role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return role

@app.post("/api/v1/knowledge/upload")
async def kb_upload(request: Request, file: UploadFile = File(...),
                    category: str = Form("02_维护操作规范")):
    role = request.headers.get("X-User-Role", "operator")
    if category not in DIR_COLLECTION:
        raise HTTPException(400, f"无效分类，可选: {list(DIR_COLLECTION)}")
    pending = Path(settings.knowledge["pending_dir"]) / category
    pending.mkdir(parents=True, exist_ok=True)
    dest = pending / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    doc_id = await memory.add_kb_doc(file.filename, str(dest), category, role)
    return {"doc_id": doc_id, "status": "PENDING"}

@app.get("/api/v1/knowledge/docs")
async def kb_docs(status: str | None = None):
    return {"docs": await memory.list_kb_docs(status)}

@app.post("/api/v1/knowledge/docs/{doc_id}/review")
async def kb_review(doc_id: int, request: Request):
    _check_role(request, "admin")
    body = await req_body(request)
    action = body.get("action")          # approve | reject
    comment = body.get("comment", "")
    doc = await memory.get_kb_doc(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if action == "approve":
        # 移入正式知识库目录
        src = Path(doc["file_path"])
        target_dir = Path(settings.knowledge["approved_dir"]) / doc["category"]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        shutil.move(str(src), str(target))
        await memory.update_kb_status(doc_id, "APPROVED", comment)
        # 更新 file_path 指向正式目录
        from src.memory.store import memory as mem
        db = await mem._db()
        try:
            await db.execute("UPDATE kb_docs SET file_path=? WHERE id=?",
                             (str(target), doc_id))
            await db.commit()
        finally:
            await db.close()
        return {"doc_id": doc_id, "status": "APPROVED",
                "file_path": str(target)}
    elif action == "reject":
        await memory.update_kb_status(doc_id, "REJECTED", comment)
        return {"doc_id": doc_id, "status": "REJECTED", "comment": comment}
    else:
        raise HTTPException(400, "action 仅支持 approve | reject")


@app.post("/api/v1/knowledge/docs/{doc_id}/ingest")
async def kb_ingest(doc_id: int, request: Request):
    """审核通过后执行入库（分块+向量化）。"""
    _check_role(request, "admin")
    from src.rag.ingest import ingest_approved_doc
    result = await ingest_approved_doc(doc_id)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.delete("/api/v1/knowledge/docs/{doc_id}")
async def kb_delete(doc_id: int, request: Request):
    """删除已入库文档（从 ChromaDB 移除向量）。"""
    _check_role(request, "admin")
    doc = await memory.get_kb_doc(doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc["status"] == "ACTIVE":
        collection = DIR_COLLECTION.get(doc["category"], "maintenance_guide")
        source = str(Path(doc["file_path"]).relative_to(
            Path(settings.knowledge["approved_dir"])))
        await asyncio.to_thread(rag_engine.delete_by_source,
                                collection, source)
    await memory.update_kb_status(doc_id, "DELETED", "管理员删除")
    # 物理文件保留（审计需要），仅标记状态
    return {"doc_id": doc_id, "status": "DELETED"}


@app.post("/api/v1/knowledge/search")
async def kb_search(request: Request):
    """知识库检索测试（运维人员验证检索效果）。"""
    body = await req_body(request)
    query = body.get("query", "")
    collection = body.get("collection")
    top_k = body.get("top_k", 5)
    if not query:
        raise HTTPException(400, "query 不能为空")
    hits = await rag_engine.hybrid_search(query, collection, top_k)
    return {"query": query, "hits": hits, "count": len(hits)}


# ───────────────────────── 插件管理 ─────────────────────────
@app.get("/api/v1/plugins")
async def get_plugins():
    return {"plugins": list_plugins()}

@app.post("/api/v1/plugins/reload")
async def post_plugins_reload(request: Request):
    _check_role(request, "admin")
    return reload_plugins()


# ───────────────────────── 系统状态 ─────────────────────────
@app.get("/api/v1/health")
async def health():
    backend_ok = await backend.health()
    return {
        "status": "ok" if not backend.offline else "degraded",
        "version": settings.app["version"],
        "backend_up": backend_ok,
        "offline_mode": backend.offline,
    }

@app.get("/api/v1/status")
async def status():
    return {
        "backend": {"up": not backend.offline,
                    "base_url": settings.backend["base_url"]},
        "llm": {"model": settings.llm["model"],
                "base_url": settings.llm["base_url"]},
        "rag": {"chromadb_path": settings.rag["chromadb_path"]},
        "plugins": list_plugins(),
        "reports_dir": str(REPORT_DIR),
    }


# ───────────────────────── 可观测性 API (§17.6.2 运行看板) ─────────────────────────
@app.get("/api/v1/observability/metrics")
async def obs_metrics():
    """返回当前指标快照（请求数/延迟/错误率/Sub-Agent分布）。"""
    obs = get_observability(settings.app["log_dir"])
    snapshot = obs.metrics.snapshot()
    # 附加 LLM 状态
    backend_ok = await backend.health()
    return {
        "metrics": snapshot,
        "system": {
            "backend_up": backend_ok,
            "offline_mode": backend.offline,
            "llm_model": settings.llm.get("model", "unknown"),
            "embedding_model": settings.rag.get("embedding_model", "unknown"),
            "version": settings.app["version"],
        },
    }


@app.get("/api/v1/observability/traces")
async def obs_traces(limit: int = 20):
    """返回最近 N 条 trace 记录。"""
    obs = get_observability(settings.app["log_dir"])
    import sqlite3
    try:
        conn = sqlite3.connect(obs.trace_store._db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trace_id, start_time, end_time, operation, status "
            "FROM traces ORDER BY start_time DESC LIMIT ?", (limit,)
        ).fetchall()
        conn.close()
        return {"traces": [dict(r) for r in rows]}
    except Exception as e:
        return {"traces": [], "error": str(e)}


@app.get("/api/v1/observability/traces/{trace_id}")
async def obs_trace_detail(trace_id: str):
    """返回指定 trace 的所有 span。"""
    obs = get_observability(settings.app["log_dir"])
    spans = obs.trace_store.get_trace(trace_id)
    return {"trace_id": trace_id, "spans": spans}


# ───────────────────────── 光纤数据代理（前端 → C++后端） ─────────────────────────
@app.get("/api/v1/fibers/stats/realtime")
async def proxy_stats_realtime():
    logger.debug("[Proxy] GET /fibers/stats/realtime")
    try:
        result = await backend.get_stats_realtime()
        logger.debug("[Proxy] /fibers/stats/realtime -> ok")
        return result
    except BackendUnavailable as e:
        logger.error("[Proxy] /fibers/stats/realtime BackendUnavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /fibers/stats/realtime error: %s", e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/fibers/stats/trend")
async def proxy_stats_trend(start_time: str, end_time: str):
    logger.debug("[Proxy] GET /fibers/stats/trend start=%s end=%s", start_time, end_time)
    try:
        result = await backend.get_stats_trend(start_time, end_time)
        logger.debug("[Proxy] /fibers/stats/trend -> ok")
        return result
    except BackendUnavailable as e:
        logger.error("[Proxy] /fibers/stats/trend BackendUnavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /fibers/stats/trend error: %s", e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/fibers/colored")
async def proxy_colored_fibers(color: str):
    logger.debug("[Proxy] GET /fibers/colored color=%s", color)
    try:
        result = await backend.get_colored(color)
        logger.debug("[Proxy] /fibers/colored -> ok")
        return result
    except ValueError as e:
        logger.warning("[Proxy] /fibers/colored ValueError: %s", e)
        raise HTTPException(400, str(e))
    except BackendUnavailable as e:
        logger.error("[Proxy] /fibers/colored BackendUnavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /fibers/colored error: %s", e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/fibers/colored/all")
async def proxy_all_colored_fibers():
    logger.debug("[Proxy] GET /fibers/colored/all")
    try:
        result = await backend.get_all_colored()
        logger.debug("[Proxy] /fibers/colored/all -> ok")
        return result
    except BackendUnavailable as e:
        logger.error("[Proxy] /fibers/colored/all BackendUnavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /fibers/colored/all error: %s", e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/fibers/{fiber_id}/performance")
async def proxy_fiber_performance(fiber_id: int):
    logger.debug("[Proxy] GET /fibers/%d/performance", fiber_id)
    try:
        result = await backend.get_performance(fiber_id)
        logger.debug("[Proxy] /fibers/%d/performance -> ok", fiber_id)
        return result
    except ValueError as e:
        logger.warning("[Proxy] /fibers/%d/performance ValueError: %s", fiber_id, e)
        raise HTTPException(400, str(e))
    except BackendUnavailable as e:
        logger.error("[Proxy] /fibers/%d/performance BackendUnavailable: %s", fiber_id, e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /fibers/%d/performance error: %s", fiber_id, e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/fibers/{fiber_id}/spanloss")
async def proxy_fiber_spanloss(fiber_id: int):
    logger.debug("[Proxy] GET /fibers/%d/spanloss", fiber_id)
    try:
        result = await backend.get_spanloss(fiber_id)
        logger.debug("[Proxy] /fibers/%d/spanloss -> ok", fiber_id)
        return result
    except ValueError as e:
        logger.warning("[Proxy] /fibers/%d/spanloss ValueError: %s", fiber_id, e)
        raise HTTPException(400, str(e))
    except BackendUnavailable as e:
        logger.error("[Proxy] /fibers/%d/spanloss BackendUnavailable: %s", fiber_id, e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /fibers/%d/spanloss error: %s", fiber_id, e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/alarms/current")
async def proxy_current_alarms(board_id: int | None = None, port_id: int | None = None):
    logger.debug("[Proxy] GET /alarms/current board_id=%s port_id=%s", board_id, port_id)
    try:
        result = await backend.get_alarms(board_id, port_id)
        logger.debug("[Proxy] /alarms/current -> ok")
        return result
    except BackendUnavailable as e:
        logger.error("[Proxy] /alarms/current BackendUnavailable: %s", e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /alarms/current error: %s", e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/topology/fibers/{fiber_id}")
async def proxy_fiber_topology(fiber_id: int):
    logger.debug("[Proxy] GET /topology/fibers/%d", fiber_id)
    try:
        result = await backend.get_fiber(fiber_id)
        logger.debug("[Proxy] /topology/fibers/%d -> ok", fiber_id)
        return result
    except ValueError as e:
        logger.warning("[Proxy] /topology/fibers/%d ValueError: %s", fiber_id, e)
        raise HTTPException(400, str(e))
    except BackendUnavailable as e:
        logger.error("[Proxy] /topology/fibers/%d BackendUnavailable: %s", fiber_id, e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /topology/fibers/%d error: %s", fiber_id, e)
        raise HTTPException(500, str(e))

@app.get("/api/v1/topology/fibers/{fiber_id}/scene")
async def proxy_fiber_scene(fiber_id: int):
    logger.debug("[Proxy] GET /topology/fibers/%d/scene", fiber_id)
    try:
        result = await backend.get_fiber_scene(fiber_id)
        logger.debug("[Proxy] /topology/fibers/%d/scene -> ok", fiber_id)
        return result
    except ValueError as e:
        logger.warning("[Proxy] /topology/fibers/%d/scene ValueError: %s", fiber_id, e)
        raise HTTPException(400, str(e))
    except BackendUnavailable as e:
        logger.error("[Proxy] /topology/fibers/%d/scene BackendUnavailable: %s", fiber_id, e)
        raise HTTPException(503, str(e))
    except Exception as e:
        logger.error("[Proxy] /topology/fibers/%d/scene error: %s", fiber_id, e)
        raise HTTPException(500, str(e))


# ───────────────────────── WebSocket 代理（前端 → C++后端） ─────────────────────────
@app.websocket("/ws/v1/events")
async def ws_proxy(websocket: WebSocket):
    await websocket.accept()
    logger.info("[WS] 前端 WebSocket 已连接")
    ws_url = settings.backend["ws_url"].replace("ws://", "ws://")
    try:
        async with websockets.connect(ws_url + "/ws/v1/events") as backend_ws:
            logger.info("[WS] 后端 WebSocket 已连接 url=%s", ws_url)

            async def forward_from_backend():
                async for message in backend_ws:
                    logger.debug("[WS] 后端→前端 msg_len=%d", len(message))
                    await websocket.send_text(message)

            async def forward_from_frontend():
                while True:
                    data = await websocket.receive_text()
                    logger.debug("[WS] 前端→后端 msg_len=%d", len(data))
                    await backend_ws.send(data)

            task1 = asyncio.create_task(forward_from_backend())
            task2 = asyncio.create_task(forward_from_frontend())

            try:
                await asyncio.gather(task1, task2)
            except Exception as e:
                logger.info("[WS] 连接断开: %s", e)
    except Exception as e:
        logger.error("[WS] 后端连接失败: %s", e)
    finally:
        logger.info("[WS] 前端 WebSocket 已断开")


# ───────────────────────── 辅助 ─────────────────────────
async def req_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}