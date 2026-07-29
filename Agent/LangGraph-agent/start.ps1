# ============================================================
# Fiber Maintenance Agent - One-Click Startup Script (Windows)
# ============================================================
# Usage: .\start.ps1 [-SkipBackend] [-SkipAgent] [-SkipFrontend]
# ============================================================

param(
    [switch]$SkipBackend,
    [switch]$SkipAgent,
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$ROOT = $PSScriptRoot
$SERVICES_ROOT = Join-Path $ROOT ".." ".." "Services"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "  ==> $msg" -ForegroundColor Cyan
    Write-Host ""
}

function Test-Command($cmd) {
    try { Get-Command $cmd -ErrorAction Stop | Out-Null; return $true }
    catch { return $false }
}

# ── 0. Pre-flight checks ──────────────────────────────────
Write-Step "Pre-flight checks"

if (-not (Test-Command "python")) {
    Write-Host "[ERROR] Python not found. Please install Python 3.11+" -ForegroundColor Red
    exit 1
}
$pyVer = (python --version 2>&1) -replace "Python ", ""
Write-Host "  Python: $pyVer"

if (-not (Test-Command "node")) {
    Write-Host "[ERROR] Node.js not found. Please install Node.js 18+" -ForegroundColor Red
    exit 1
}
$nodeVer = (node --version 2>&1)
Write-Host "  Node.js: $nodeVer"

# ── 1. Environment file ───────────────────────────────────
$envFile = Join-Path $ROOT ".env"
$envExample = Join-Path $ROOT ".env.example"
if (-not (Test-Path $envFile)) {
    Write-Step "Creating .env from .env.example"
    Copy-Item $envExample $envFile
    Write-Host "  .env created. Please review and edit it." -ForegroundColor Yellow
}

# ── 2. C++ Backend (via WSL) ──────────────────────────────
if (-not $SkipBackend) {
    Write-Step "Starting C++ Backend (WSL)"

    $startScript = Join-Path $SERVICES_ROOT "scripts" "start_services.sh"
    if (Test-Path $startScript) {
        $wslCmd = "cd /mnt/$($ROOT.Replace('\','/').Replace(':',''))/../../Services && bash scripts/start_services.sh"
        Start-Process wsl -ArgumentList "-e", "bash", "-c", $wslCmd -WindowStyle Minimized
        Write-Host "  Backend starting in WSL (minimized window)..."
        Write-Host "  Waiting 5s for backend to initialize..."
        Start-Sleep -Seconds 5
    } else {
        Write-Host "  [WARN] start_services.sh not found at $startScript" -ForegroundColor Yellow
        Write-Host "  Skipping backend startup." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [SKIP] Backend startup skipped." -ForegroundColor DarkGray
}

# ── 3. Python dependencies ────────────────────────────────
if (-not $SkipAgent) {
    Write-Step "Installing Python dependencies"
    Set-Location $ROOT
    python -m pip install -e ".[dev]" --quiet
    Write-Host "  Python dependencies installed."
}

# ── 4. LangGraph Agent Server ─────────────────────────────
if (-not $SkipAgent) {
    Write-Step "Starting LangGraph Agent Server (port 8000)"
    $agentJob = Start-Process python -ArgumentList "-m", "uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "8000", "--reload" `
        -WorkingDirectory $ROOT -WindowStyle Minimized -PassThru
    Write-Host "  Agent server starting (PID: $($agentJob.Id))..."
    Start-Sleep -Seconds 3
} else {
    Write-Host "  [SKIP] Agent server startup skipped." -ForegroundColor DarkGray
}

# ── 5. Frontend ───────────────────────────────────────────
if (-not $SkipFrontend) {
    $frontendDir = Join-Path $ROOT "frontend"
    if (Test-Path $frontendDir) {
        Write-Step "Installing frontend dependencies"
        Set-Location $frontendDir
        npm install --silent 2>$null

        Write-Step "Starting frontend dev server (port 5173)"
        Start-Process npm -ArgumentList "run", "dev" -WorkingDirectory $frontendDir -WindowStyle Normal

        Start-Sleep -Seconds 3
        Write-Host "  Opening browser..."
        Start-Process "http://localhost:5173"
    } else {
        Write-Host "  [WARN] frontend/ directory not found." -ForegroundColor Yellow
    }
} else {
    Write-Host "  [SKIP] Frontend startup skipped." -ForegroundColor DarkGray
}

# ── Done ──────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  All services started!" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:       http://localhost:5173" -ForegroundColor Cyan
Write-Host "  Agent API:      http://localhost:8000" -ForegroundColor Cyan
Write-Host "  C++ Backend:    http://localhost:8080" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Press Ctrl+C to stop (frontend/agent only)." -ForegroundColor DarkGray
Write-Host "  Backend runs in separate WSL window." -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

Set-Location $ROOT
