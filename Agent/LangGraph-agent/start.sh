#!/usr/bin/env bash
# ============================================================
# Fiber Maintenance Agent - One-Click Startup Script (Linux/WSL)
# ============================================================
# Usage: ./start.sh [--skip-backend] [--skip-agent] [--skip-frontend]
# ============================================================

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
SERVICES_ROOT="$ROOT/../../Services"

SKIP_BACKEND=false
SKIP_AGENT=false
SKIP_FRONTEND=false

for arg in "$@"; do
    case $arg in
        --skip-backend)  SKIP_BACKEND=true ;;
        --skip-agent)    SKIP_AGENT=true ;;
        --skip-frontend) SKIP_FRONTEND=true ;;
    esac
done

step() {
    echo ""
    echo -e "  \033[36m==>\033[0m $1"
    echo ""
}

# ── 0. Pre-flight checks ──────────────────────────────────
step "Pre-flight checks"

if ! command -v python3 &>/dev/null; then
    echo -e "\033[31m[ERROR] Python3 not found.\033[0m"
    exit 1
fi
echo "  Python: $(python3 --version)"

if ! command -v node &>/dev/null; then
    echo -e "\033[31m[ERROR] Node.js not found.\033[0m"
    exit 1
fi
echo "  Node.js: $(node --version)"

# ── 1. Environment file ───────────────────────────────────
if [ ! -f "$ROOT/.env" ]; then
    step "Creating .env from .env.example"
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "  .env created. Please review and edit it."
fi

# ── 2. C++ Backend ────────────────────────────────────────
if [ "$SKIP_BACKEND" = false ]; then
    step "Starting C++ Backend"
    START_SCRIPT="$SERVICES_ROOT/scripts/start_services.sh"
    if [ -f "$START_SCRIPT" ]; then
        cd "$SERVICES_ROOT"
        bash scripts/start_services.sh &
        BACKEND_PID=$!
        cd "$ROOT"
        echo "  Backend starting (PID: $BACKEND_PID)..."
        sleep 5
    else
        echo -e "\033[33m  [WARN] start_services.sh not found. Skipping backend.\033[0m"
    fi
else
    echo "  [SKIP] Backend startup skipped."
fi

# ── 3. Python dependencies ────────────────────────────────
if [ "$SKIP_AGENT" = false ]; then
    step "Installing Python dependencies"
    cd "$ROOT"
    pip install -e ".[dev]" --quiet 2>/dev/null || pip3 install -e ".[dev]" --quiet
    echo "  Python dependencies installed."
fi

# ── 4. LangGraph Agent Server ─────────────────────────────
if [ "$SKIP_AGENT" = false ]; then
    step "Starting LangGraph Agent Server (port 8000)"
    cd "$ROOT"
    python3 -m uvicorn src.server:app --host 0.0.0.0 --port 8000 --reload &
    AGENT_PID=$!
    echo "  Agent server starting (PID: $AGENT_PID)..."
    sleep 3
else
    echo "  [SKIP] Agent server startup skipped."
fi

# ── 5. Frontend ───────────────────────────────────────────
if [ "$SKIP_FRONTEND" = false ]; then
    FRONTEND_DIR="$ROOT/frontend"
    if [ -d "$FRONTEND_DIR" ]; then
        step "Installing frontend dependencies"
        cd "$FRONTEND_DIR"
        npm install --silent 2>/dev/null

        step "Starting frontend dev server (port 5173)"
        npm run dev &
        FRONTEND_PID=$!
        sleep 3
    else
        echo -e "\033[33m  [WARN] frontend/ directory not found.\033[0m"
    fi
else
    echo "  [SKIP] Frontend startup skipped."
fi

# ── Done ──────────────────────────────────────────────────
cd "$ROOT"
echo ""
echo -e "\033[32m============================================================\033[0m"
echo -e "\033[32m  All services started!\033[0m"
echo ""
echo -e "  Frontend:       \033[36mhttp://localhost:5173\033[0m"
echo -e "  Agent API:      \033[36mhttp://localhost:8000\033[0m"
echo -e "  C++ Backend:    \033[36mhttp://localhost:8080\033[0m"
echo ""
echo -e "  Press Ctrl+C to stop all services."
echo -e "\033[32m============================================================\033[0m"
echo ""

# ── Wait for Ctrl+C ───────────────────────────────────────
cleanup() {
    echo ""
    echo "Shutting down..."
    [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null
    [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    echo "All services stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Wait for all background processes
wait
