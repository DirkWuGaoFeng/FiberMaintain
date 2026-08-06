"""
Fiber Maintenance Agent Server — v7.2-Final.

FastAPI application with:
  POST /fiber-agent/invoke   - Synchronous invocation
  POST /fiber-agent/stream   - Streaming invocation
  GET  /health               - Health check (multi-component)
  GET  /metrics              - Prometheus metrics
  POST /api/v1/rules/reload  - Hot-reload rule engine
  POST /api/v1/skills/reload - Hot-reload skill system (atomic)
  GET  /api/v1/skills        - List loaded skills
  GET  /api/batch/{thread_id}/progress - Batch progress query

Startup:
  - Initialize EventListener + EventRouter
  - Initialize DegradationManager (background probe)
  - Initialize LocalCache
  - Initialize SkillLoader (skills/ YAML)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

VERSION = "7.2.0"

# 主图已知的 19 个节点 ID（用于从 SSE 事件中提取节点执行跟踪）
_GRAPH_NODE_NAMES = frozenset([
    "input_guard", "rule_engine", "fast_path_executor", "intent_classifier",
    "param_gate", "clarification", "intent_router", "data_collector",
    "rule_judgment", "analysis_expert", "narrator", "narrator_validator",
    "template_fallback", "report_generator", "report_evaluator",
    "batch_dispatcher", "knowledge_qa", "result_aggregator", "degradation_handler",
])

# 活动 span 跟踪（按节点名存储开始时间）
_active_node_spans: dict[str, float] = {}


def _trace_event_to_spans(tracer, event: dict) -> None:
    """从 LangGraph astream_events 事件中提取节点执行信息，记录到 tracer。

    监听 on_chain_start / on_chain_end 事件，仅处理主图节点。
    工具调用和 LLM 调用也作为子 span 记录。
    """
    event_type = event.get("event", "")
    name = event.get("name", "")

    if event_type == "on_chain_start" and name in _GRAPH_NODE_NAMES:
        # 节点开始 — 记录开始时间
        _active_node_spans[name] = time.time()

    elif event_type == "on_chain_end" and name in _GRAPH_NODE_NAMES:
        # 节点结束 — 计算耗时并记录 span
        start = _active_node_spans.pop(name, None)
        if start is not None:
            duration_ms = round((time.time() - start) * 1000, 2)
            # 提取输出摘要
            output = event.get("data", {}).get("output", {})
            output_summary = ""
            if isinstance(output, dict):
                parts = []
                if output.get("intent"):
                    parts.append(f"intent={output['intent']}")
                if output.get("processing_path"):
                    parts.append(f"path={output['processing_path']}")
                if output.get("final_output"):
                    parts.append(f"output_len={len(str(output['final_output']))}")
                if output.get("rule_match"):
                    rm = output["rule_match"]
                    parts.append(f"rule={rm.get('intent', '?') if isinstance(rm, dict) else '?'}")
                output_summary = ", ".join(parts)

            # 直接记录为已完成的 span（不使用 context manager，因为是事后记录）
            tracer._span_counter += 1
            from .observability.request_tracer import TraceSpan, SLOW_SPAN_THRESHOLD_MS
            span = TraceSpan(
                span_id=f"{tracer.trace_id}-{tracer._span_counter:03d}",
                node_name=name,
                start_time=start,
                end_time=time.time(),
                duration_ms=duration_ms,
                output_summary=output_summary[:300],
                is_slow=duration_ms > SLOW_SPAN_THRESHOLD_MS,
            )
            tracer.spans.append(span)

            if span.is_slow:
                logger.warning(
                    f"[TRACE:{tracer.trace_id}] [{name}] ⚠ SLOW {duration_ms}ms"
                )

    elif event_type == "on_tool_end":
        # 工具调用结束 — 记录为子 span
        duration_ms = 0  # SSE 事件不提供工具耗时，记录名称和结果
        result = str(event.get("data", {}).get("output", ""))[:200]
        tracer.record_tool_call(
            tool_name=name,
            duration_ms=duration_ms,
            result_summary=result,
            success=True,
        )


@asynccontextmanager
async def lifespan(app):
    """Application lifespan: startup and shutdown hooks."""
    # === Startup ===
    logger.info(f"[Server] Starting Fiber Maintenance Agent v{VERSION}")

    # Initialize LocalCache
    try:
        from .cache.local_cache import create_local_cache
        await create_local_cache()
        logger.info("[Server] LocalCache initialized")
    except Exception as e:
        logger.warning(f"[Server] LocalCache init failed: {e}")

    # Initialize EventListener + Router
    try:
        from .events.listener import create_event_listener
        from .events.router import get_event_router

        listener = create_event_listener()
        router = get_event_router()
        await listener.start()
        await router.start(listener.queue)
        logger.info("[Server] EventListener + Router started")
    except Exception as e:
        logger.warning(f"[Server] Event system init failed: {e}")

    # Initialize DegradationManager
    try:
        from .resilience.degradation import create_degradation_manager
        dm = create_degradation_manager()
        await dm.start()
        logger.info("[Server] DegradationManager started")
    except Exception as e:
        logger.warning(f"[Server] DegradationManager init failed: {e}")

    # Initialize RAG Engine (hybrid retrieval)
    try:
        from .rag.engine import get_rag_engine
        rag_engine = get_rag_engine()
        ok = await rag_engine.initialize()
        if ok:
            logger.info("[Server] RAG Engine initialized (hybrid retrieval ready)")
        else:
            logger.warning("[Server] RAG Engine initialized but retriever unavailable")
    except Exception as e:
        logger.warning(f"[Server] RAG Engine init failed: {e}")

    # Initialize Skill System (YAML-driven triggers/routing/judgment)
    try:
        from .skills.loader import get_skill_loader
        loader = get_skill_loader()
        skill_count = len(loader.all_skills())
        logger.info(f"[Server] Skill system initialized ({skill_count} skills)")
    except Exception as e:
        logger.warning(f"[Server] Skill system init failed: {e}")

    yield

    # === Shutdown ===
    logger.info("[Server] Shutting down...")
    try:
        from .events.listener import get_event_listener
        from .events.router import get_event_router
        from .resilience.degradation import get_degradation_manager

        listener = get_event_listener()
        if listener:
            await listener.stop()
        router = get_event_router()
        await router.stop()
        dm = get_degradation_manager()
        if dm:
            await dm.stop()
    except Exception as e:
        logger.debug(f"[Server] Shutdown cleanup: {e}")


def create_app():
    """Create the FastAPI application with all v7.1 routes."""
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="Fiber Maintenance Agent",
        version=VERSION,
        description="Intelligent fiber maintenance agent — LangGraph v7.1-Final",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ===== Health Check (Enhanced v7.1) =====
    @app.get("/health")
    async def health():
        """Enhanced health check — returns status of all components.

        Response format:
        {
            "agent": "ok",
            "version": "7.1.0",
            "ollama": {"status": "ok", "models": [...], "latency_ms": 12},
            "cpp_backend": {"status": "ok", "latency_ms": 2},
            "circuit_breaker": "closed",
            "degradation_level": 0
        }
        """
        import httpx

        result = {
            "agent": "ok",
            "version": VERSION,
        }

        # 检查 LLM 服务状态：按层级实际使用的 provider 分别探测
        # （主模型可走百炼 openai 协议，次级/兜底可走本地 ollama）
        from .config import LLM_CONFIG, OPENAI_API_BASE, OPENAI_API_KEY

        providers_in_use = {cfg.provider for cfg in LLM_CONFIG.values()}

        # 本地 Ollama（仅当有层级使用时探测）
        if "ollama" in providers_in_use:
            try:
                start = time.time()
                async with httpx.AsyncClient() as client:
                    resp = await client.get("http://localhost:11434/api/tags", timeout=3.0)
                    latency = int((time.time() - start) * 1000)
                    if resp.status_code == 200:
                        models = [m.get("name", "") for m in resp.json().get("models", [])]
                        result["ollama"] = {"status": "ok", "models": models, "latency_ms": latency}
                    else:
                        result["ollama"] = {"status": "error", "http_status": resp.status_code}
            except Exception as e:
                result["ollama"] = {"status": "unavailable", "error": str(e)[:100]}
        else:
            result["ollama"] = {"status": "skipped", "note": "no tier uses ollama"}

        # OpenAI 兼容 API（阿里云百炼，仅当有层级使用时探测）
        if "openai" in providers_in_use:
            try:
                start = time.time()
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{OPENAI_API_BASE}/models",
                        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                        timeout=5.0,
                    )
                    latency = int((time.time() - start) * 1000)
                    if resp.status_code == 200:
                        models = [m.get("id", "") for m in resp.json().get("data", [])]
                        result["llm_api"] = {
                            "status": "ok",
                            "provider": "openai-compatible",
                            "base_url": OPENAI_API_BASE,
                            "models_count": len(models),
                            "latency_ms": latency,
                        }
                    else:
                        result["llm_api"] = {
                            "status": "error",
                            "provider": "openai-compatible",
                            "http_status": resp.status_code,
                        }
            except Exception as e:
                result["llm_api"] = {"status": "unavailable", "error": str(e)[:100]}

        # 检查 C++ 后端状态
        try:
            start = time.time()
            async with httpx.AsyncClient() as client:
                resp = await client.get("http://localhost:8080/health", timeout=3.0)
                latency = int((time.time() - start) * 1000)
                if resp.status_code == 200:
                    result["cpp_backend"] = {"status": "ok", "latency_ms": latency}
                else:
                    result["cpp_backend"] = {"status": "error", "http_status": resp.status_code}
        except Exception as e:
            result["cpp_backend"] = {"status": "unavailable", "error": str(e)[:100]}

        # 熔断器状态
        try:
            from .tools._http_client import fiber_http_client
            cb_state = fiber_http_client.circuit_breaker.state.value
            result["circuit_breaker"] = cb_state
        except Exception:
            result["circuit_breaker"] = "unknown"

        # 降级等级
        try:
            from .resilience.degradation import get_degradation_manager
            dm = get_degradation_manager()
            if dm:
                status = dm.get_status()
                result["degradation_level"] = status.get("level", 0)
            else:
                result["degradation_level"] = 0
        except Exception:
            result["degradation_level"] = 0

        return result

    # ===== Prometheus Metrics =====
    @app.get("/metrics")
    async def metrics_endpoint():
        try:
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
            from fastapi.responses import Response
            return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
        except ImportError:
            return {"error": "prometheus_client not installed"}

    # ===== Rule Engine Hot-Reload =====
    @app.post("/api/v1/rules/reload")
    async def reload_rules():
        try:
            from .nodes.rule_engine import RuleEngine
            count = RuleEngine.reload_rules()
            return {"status": "ok", "rules_loaded": count}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Skill System Hot-Reload =====
    @app.post("/api/v1/skills/reload")
    async def reload_skills():
        """Hot-reload all Skill YAML files (atomic: all-or-nothing)."""
        try:
            from .skills.loader import get_skill_loader
            loader = get_skill_loader()
            count = loader.reload()
            return {"status": "ok", "skills_loaded": count}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/skills")
    async def list_skills():
        """List all loaded skills with metadata."""
        try:
            from .skills.loader import get_skill_loader
            loader = get_skill_loader()
            skills = loader.all_skills()
            return {
                "count": len(skills),
                "skills": [
                    {
                        "id": s.id,
                        "name": s.name,
                        "version": s.version,
                        "intent": s.routing.intent,
                        "group": s.routing.group,
                        "fast_path": s.routing.fast_path_eligible,
                        "priority": s.routing.priority,
                    }
                    for s in skills
                ],
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Main Invoke Endpoint =====
    @app.post("/invoke")
    async def invoke(request: dict):
        """Primary invoke endpoint (fallback if LangServe unavailable)."""
        start_time = time.time()
        try:
            from .graph.main_graph import get_graph
            from .graph.state import create_initial_state
            from .observability.audit import write_request_audit

            graph = get_graph()
            user_msg = request.get("message", "")
            thread_id = request.get("thread_id", "default")

            if not user_msg:
                raise HTTPException(status_code=400, detail="message is required")

            state = create_initial_state(user_msg, thread_id)
            config = {"configurable": {"thread_id": thread_id}}
            result = await graph.ainvoke(state, config)

            output = result.get("final_output", "")
            latency_ms = int((time.time() - start_time) * 1000)

            # Audit log
            await write_request_audit(
                request_id=result.get("request_id", ""),
                user_input=user_msg,
                processing_path=result.get("processing_path", "normal"),
                output=output,
                latency_ms=latency_ms,
                degradation_level=result.get("degradation_level", 0),
                loop_count=result.get("loop_count", 0),
            )

            return {
                "result": output,
                "processing_path": result.get("processing_path", "normal"),
                "latency_ms": latency_ms,
                "request_id": result.get("request_id", ""),
            }
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Server] Invoke error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Frontend Management APIs (knowledge/threads/graph/memory/metrics) =====
    try:
        from .frontend_api import router as frontend_router
        app.include_router(frontend_router)
        logger.info("[Server] Frontend API routes registered")
    except Exception as e:
        logger.warning(f"[Server] Frontend API routes failed to register: {e}")

    # ===== SSE Stream Endpoint (replaces LangServe) =====
    from sse_starlette.sse import EventSourceResponse

    # SSE 流全局超时（秒）— v7.2: 默认 120s 以适应 LLM 冷启动场景
    SSE_STREAM_TIMEOUT = int(os.environ.get("SSE_STREAM_TIMEOUT", "120"))
    # 心跳间隔（秒）
    SSE_HEARTBEAT_INTERVAL = int(os.environ.get("SSE_HEARTBEAT_INTERVAL", "5"))

    @app.post("/fiber-agent/stream")
    async def fiber_agent_stream(request: dict):
        """SSE streaming endpoint — compatible with frontend sse.ts event parsing.

        v7.2: Integrated full-chain RequestTracer for per-node timing and bottleneck detection.
        Added global timeout (60s) + heartbeat (5s) to prevent infinite hang.
        """
        from .graph.main_graph import get_graph
        from .graph.state import create_initial_state
        from .observability.request_tracer import RequestTracer
        from .observability.metrics import metrics

        # Parse LangServe-style request: {input: {messages, thread_id, user_input}, config: {...}}
        inp = request.get("input", {})
        user_msg = inp.get("user_input", "")
        if not user_msg:
            msgs = inp.get("messages", [])
            user_msg = msgs[-1]["content"] if msgs else ""
        thread_id = (
            inp.get("thread_id", "")
            or request.get("config", {}).get("configurable", {}).get("thread_id", "default")
        )

        if not user_msg:
            raise HTTPException(status_code=400, detail="message is required")

        graph = get_graph()
        state = create_initial_state(user_msg, thread_id)
        config = {"configurable": {"thread_id": thread_id}}

        # 创建全链路跟踪器（使用 state 中生成的 trace_id）
        tracer = RequestTracer(user_input=user_msg, trace_id=state.get("trace_id"))

        async def event_generator():
            start_time = time.time()
            last_heartbeat = start_time
            final_output = ""  # Track final output for dedicated event
            processing_path = "normal"

            try:
                # 使用 asyncio.timeout 实现全局超时保护
                async with asyncio.timeout(SSE_STREAM_TIMEOUT):
                    async for event in graph.astream_events(state, config=config, version="v2"):
                        now = time.time()

                        # 捕获 final_output（从 result_aggregator 或 fast_path_executor）
                        if (event.get("event") == "on_chain_end"
                                and event.get("name") in ("result_aggregator", "fast_path_executor")):
                            output = event.get("data", {}).get("output", {})
                            if isinstance(output, dict) and output.get("final_output"):
                                final_output = output["final_output"]
                            if isinstance(output, dict) and output.get("processing_path"):
                                processing_path = output["processing_path"]

                        # 记录规则命中（从 rule_engine 节点输出）
                        if (event.get("event") == "on_chain_end"
                                and event.get("name") == "rule_engine"):
                            output = event.get("data", {}).get("output", {})
                            if isinstance(output, dict) and output.get("rule_match"):
                                rm = output["rule_match"]
                                rule_id = rm.get("intent", "unknown") if isinstance(rm, dict) else "unknown"
                                metrics.record_rule_hit(rule_id)

                        # 记录工具调用指标
                        if event.get("event") == "on_tool_end":
                            metrics.record_tool_call(event.get("name", "unknown"), True)
                        elif event.get("event") == "on_tool_error":
                            metrics.record_tool_call(event.get("name", "unknown"), False)

                        # 跟踪节点执行（从 SSE 事件中提取节点开始/结束）
                        _trace_event_to_spans(tracer, event)

                        # 心跳检测：超过间隔则发送心跳事件
                        if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL:
                            elapsed_ms = int((now - start_time) * 1000)
                            heartbeat = {
                                "event": "heartbeat",
                                "data": {"elapsed_ms": elapsed_ms, "status": "processing"},
                            }
                            yield {"data": json.dumps(heartbeat, ensure_ascii=False)}
                            last_heartbeat = now

                        yield {"data": json.dumps(event, ensure_ascii=False, default=str)}

                # 流正常结束后，发送 final_output 事件（前端用于填充快速路径结果）
                if final_output:
                    yield {"data": json.dumps({
                        "event": "final_output",
                        "data": {"output": final_output}
                    }, ensure_ascii=False)}

                # 完成跟踪
                tracer.finish(processing_path=processing_path, final_output=final_output)

                # 记录 Prometheus 指标
                duration_s = time.time() - start_time
                metrics.record_request(processing_path)
                metrics.observe_duration(processing_path, duration_s)

            except asyncio.TimeoutError:
                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.warning(f"[SSE] Stream timeout after {elapsed_ms}ms for thread={thread_id}")
                tracer.finish(processing_path="timeout", final_output="")
                metrics.record_request("timeout")
                metrics.observe_duration("timeout", time.time() - start_time)
                error_event = {
                    "event": "error",
                    "data": {
                        "message": f"Request timeout ({SSE_STREAM_TIMEOUT}s)",
                        "elapsed_ms": elapsed_ms,
                        "code": "TIMEOUT",
                        "trace_id": tracer.trace_id,
                    },
                }
                yield {"data": json.dumps(error_event, ensure_ascii=False)}

            except Exception as e:
                elapsed_ms = int((time.time() - start_time) * 1000)
                logger.error(f"[SSE] Stream error after {elapsed_ms}ms: {e}")
                tracer.finish(processing_path="error", final_output="")
                metrics.record_request("error")
                metrics.observe_duration("error", time.time() - start_time)
                error_event = {
                    "event": "error",
                    "data": {
                        "message": str(e),
                        "elapsed_ms": elapsed_ms,
                        "code": "INTERNAL_ERROR",
                        "trace_id": tracer.trace_id,
                    },
                }
                yield {"data": json.dumps(error_event, ensure_ascii=False)}

        return EventSourceResponse(event_generator())

    logger.info("[Server] SSE stream endpoint registered at /fiber-agent/stream")

    # ===== Trace Diagnostics API [v7.2] =====
    @app.get("/api/v1/traces")
    async def list_traces(limit: int = 20):
        """List recent trace summaries for diagnostics."""
        from .observability.request_tracer import get_recent_traces
        return {"traces": get_recent_traces(limit)}

    @app.get("/api/v1/traces/{trace_id}")
    async def get_trace_detail(trace_id: str):
        """Get full trace detail by trace_id (reads from data/traces/)."""
        from pathlib import Path
        from .config import DATA_DIR

        trace_file = Path(DATA_DIR) / "traces" / f"{trace_id}.json"
        if not trace_file.exists():
            raise HTTPException(status_code=404, detail=f"Trace not found: {trace_id}")
        try:
            return json.loads(trace_file.read_text(encoding="utf-8"))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Batch Progress =====
    @app.get("/api/batch/{thread_id}/progress")
    async def get_batch_progress(thread_id: str):
        try:
            from .graph.main_graph import get_graph
            graph = get_graph()
            state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
            if state and state.values:
                return state.values.get("batch_progress", {"status": "not_found"})
            return {"status": "not_found"}
        except Exception as e:
            return {"error": str(e)}

    # ===== Degradation Status =====
    @app.get("/api/v1/degradation")
    async def degradation_status():
        try:
            from .resilience.degradation import get_degradation_manager
            dm = get_degradation_manager()
            if dm:
                return dm.get_status()
            return {"level": 0, "note": "manager not initialized"}
        except Exception as e:
            return {"error": str(e)}

    return app


# Module-level app instance for uvicorn
app = create_app()


# ===== WebSocket Endpoint (defined at module level for proper registration) =====
from fastapi import WebSocket as _WS, WebSocketDisconnect as _WSD


@app.websocket("/ws/v1/events")
async def ws_events_endpoint(websocket: _WS):
    """WebSocket endpoint for real-time event push (heartbeat + future alarms)."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except _WSD:
        pass


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("AGENT_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENT_PORT", "8000"))
    uvicorn.run("src.server:app", host=host, port=port, reload=True)
