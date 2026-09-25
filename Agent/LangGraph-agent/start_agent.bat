@echo off
chcp 65001 >nul
title Fiber Maintenance Agent v7.1

echo ============================================
echo   Fiber Maintenance Agent v7.1-Final
echo   Windows 一键启动脚本 (后端 + 前端)
echo ============================================
echo.

:: ===== 1. 检查 Python 环境 =====
echo [1/8] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未安装或不在 PATH 中！
    echo 请安装 Python 3.11+ 并添加到 PATH
    pause
    exit /b 1
)
echo   √ Python 已就绪

:: ===== 2. 检查虚拟环境 =====
echo [2/8] 检查虚拟环境...
if not exist ".venv\Scripts\activate.bat" (
    echo   创建虚拟环境...
    python -m venv .venv
)
call .venv\Scripts\activate
echo   √ 虚拟环境已激活

:: ===== 3. 检查依赖 =====
echo [3/8] 检查依赖包...
pip show langgraph >nul 2>&1
if errorlevel 1 (
    echo   安装依赖...
    pip install -e ".[dev]" --quiet
)
echo   √ 依赖已就绪

:: ===== 4. 检查 Ollama 服务 =====
echo [4/8] 检查 Ollama 服务...
ollama list >nul 2>&1
if errorlevel 1 (
    echo [WARN] Ollama 未运行！Agent 将以降级模式启动。
    echo   请启动 Ollama: ollama serve
    echo   拉取模型: ollama pull qwen2.5:14b
    echo             ollama pull qwen2.5:7b
    echo             ollama pull qwen2.5:3b
    echo.
) else (
    echo   √ Ollama 服务正常
    :: 检查模型是否存在
    ollama list | findstr "qwen2.5:14b" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] qwen2.5:14b 未下载，正在拉取...
        ollama pull qwen2.5:14b
    )
    ollama list | findstr "qwen2.5:7b" >nul 2>&1
    if errorlevel 1 (
        echo [WARN] qwen2.5:7b 未下载，正在拉取...
        ollama pull qwen2.5:7b
    )
)

:: ===== 5. 检查 .env 配置 =====
echo [5/8] 检查配置文件...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo   √ 已从 .env.example 创建 .env
        echo   请根据需要修改 .env 配置
    ) else (
        echo [WARN] 未找到 .env 配置文件，使用默认配置
    )
) else (
    echo   √ .env 配置已就绪
)

:: ===== 6. 检查 Node.js 环境 =====
echo [6/8] 检查 Node.js 环境...
node --version >nul 2>&1
if errorlevel 1 (
    echo [WARN] Node.js 未安装！前端开发服务器将无法启动。
    echo   请安装 Node.js 18+: https://nodejs.org
    set FRONTEND_AVAILABLE=0
) else (
    echo   √ Node.js 已就绪
    set FRONTEND_AVAILABLE=1
)

:: ===== 7. 前端依赖准备 =====
if not "%FRONTEND_AVAILABLE%"=="1" (
    echo [7/8] 跳过前端 (Node.js 不可用)
    goto :skip_frontend
)
echo [7/8] 准备前端开发服务器...
if exist "frontend\node_modules" (
    echo   √ 前端依赖已就绪
    goto :skip_frontend
)
echo   安装前端依赖 (首次可能需要几分钟)...
pushd frontend
call npm install
if errorlevel 1 (
    echo [ERROR] npm install 失败！请检查网络连接。
    popd
    set FRONTEND_AVAILABLE=0
    goto :skip_frontend
)
popd
echo   √ 前端依赖安装完成
:skip_frontend

:: ===== 8. 端口占用检测 =====
echo.
echo [8/8] 检测端口占用...

:: --- 检测后端端口（从 .env 读取 AGENT_PORT，默认 8200）---
set "AGENT_PORT=8200"
for /f "tokens=2 delims==" %%V in ('findstr /R /C:"^AGENT_PORT=" "%~dp0.env" 2^>nul') do set "AGENT_PORT=%%V"
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":%AGENT_PORT%.*LISTENING"') do set "PORT_PID=%%P"
if not defined PORT_PID (
    echo   √ 端口 %AGENT_PORT% 空闲
    goto :port_8200_ok
)
echo   [!] 端口 %AGENT_PORT% 被占用 (PID: %PORT_PID%)，正在终止...
taskkill /PID %PORT_PID% /F >nul 2>&1
if errorlevel 1 (
    echo   [WARN] 自动终止失败，请手动执行: taskkill /PID %PORT_PID% /F
    pause
    exit /b 1
)
echo   √ 已终止进程 PID %PORT_PID%，端口 %AGENT_PORT% 已释放
:port_8200_ok

:: --- 检测前端端口 5173 ---
if not "%FRONTEND_AVAILABLE%"=="1" goto :port_5173_ok
set "PORT_PID="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R ":5173.*LISTENING"') do set "PORT_PID=%%P"
if not defined PORT_PID (
    echo   √ 端口 5173 空闲
    goto :port_5173_ok
)
echo   [!] 端口 5173 被占用 (PID: %PORT_PID%)，正在终止...
taskkill /PID %PORT_PID% /F >nul 2>&1
if errorlevel 1 (
    echo   [WARN] 无法终止进程 PID %PORT_PID%，前端可能启动失败
    goto :port_5173_ok
)
echo   √ 已终止进程 PID %PORT_PID%，端口 5173 已释放
:port_5173_ok

:: ===== 启动服务 =====
echo.
echo ============================================
echo   启动 Agent 服务...
echo   Agent 后端: http://localhost:%AGENT_PORT%
if "%FRONTEND_AVAILABLE%"=="1" echo   前端界面:   http://127.0.0.1:5173
echo   健康检查: http://localhost:%AGENT_PORT%/health
echo   指标: http://localhost:%AGENT_PORT%/metrics
echo ============================================
echo.
echo 按 Ctrl+C 停止服务（可能需要等待几秒）
echo.

:: 启动前端开发服务器 (新窗口)
if not "%FRONTEND_AVAILABLE%"=="1" goto :skip_frontend_start
start "Fiber Agent Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
echo   √ 前端开发服务器已在新窗口启动: http://127.0.0.1:5173
echo.
:skip_frontend_start

:: 启动后端 (当前窗口，阻塞)
:: 注意：不使用 --reload，因为 Windows 下 --reload 的子进程会吞掉 Ctrl+C 信号
:: 端口从 .env 的 AGENT_PORT 读取（8200 常被 Windows Hyper-V/WSL 动态保留区占用）
set "AGENT_PORT=8200"
for /f "tokens=2 delims==" %%V in ('findstr /R /C:"^AGENT_PORT=" "%~dp0.env" 2^>nul') do set "AGENT_PORT=%%V"
python -m uvicorn src.server:app --host 0.0.0.0 --port %AGENT_PORT%

echo.
echo Agent 服务已停止。
pause
