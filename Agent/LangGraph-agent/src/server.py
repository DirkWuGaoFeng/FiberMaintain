"""
LangServe entry point: exposes the Fiber Maintenance Agent graph as REST API.

Endpoints:
  POST /fiber-agent/invoke   - Synchronous invocation
  POST /fiber-agent/stream   - Streaming invocation
  POST /fiber-agent/batch    - Batch invocation
  GET  /api/batch/{thread_id}/progress - Batch progress query
  GET  /health               - Health check
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app():
    """Create the FastAPI application with LangServe routes."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(
        title="Fiber Maintenance Agent",
        version="5.0.0",
        description="Intelligent fiber maintenance agent based on LangChain + LangGraph",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "5.0.0"}

    # LangServe routes
    try:
        from langserve import add_routes
        from .graph.main_graph import get_graph

        graph = get_graph()
        add_routes(
            app,
            graph,
            path="/fiber-agent",
            enable_feedback_endpoint=True,
            enable_public_trace_link_endpoint=True,
        )
        logger.info("LangServe routes registered at /fiber-agent")
    except Exception as e:
        logger.error(f"Failed to register LangServe routes: {e}")
        # Fallback: register basic invoke endpoint
        from fastapi import HTTPException

        @app.post("/invoke")
        async def basic_invoke(request: dict):
            try:
                from .graph.main_graph import get_graph
                from .graph.state import create_initial_state

                graph = get_graph()
                user_msg = request.get("message", "")
                thread_id = request.get("thread_id", "default")
                state = create_initial_state(user_msg)
                config = {"configurable": {"thread_id": thread_id}}
                result = await graph.ainvoke(state, config)
                return {"result": result.get("final_report", "No response")}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

    # Custom endpoint: batch progress query
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

    return app


# Module-level app instance for uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("AGENT_HOST", "0.0.0.0")
    port = int(os.environ.get("AGENT_PORT", "8000"))
    uvicorn.run("src.server:app", host=host, port=port, reload=True)
