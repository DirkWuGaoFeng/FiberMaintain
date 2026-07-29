@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ==========================================================
::  光纤维护智能 Agent — Windows 一键启动脚本
:: ==========================================================

set "AGENT_DIR=%~dp0"
cd /d "%AGENT_DIR%"
set PYTHONUTF8=1

echo ==========================================
echo   光纤维护智能 Agent 一键启动
echo ==========================================

:: ---- 1. 检查 Python ----
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 未找到 python，请先安装 Python 3.10+
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   Python 版本: %PY_VER%

:: ---- 2. 创建虚拟环境（如不存在） ----
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo [1/5] 创建 Python 虚拟环境...
    python -m venv .venv
    if !ERRORLEVEL! neq 0 (
        echo [ERROR] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo   虚拟环境已创建
) else (
    echo [1/5] 虚拟环境已存在，跳过创建
)

:: ---- 3. 激活虚拟环境 ----
echo [2/5] 激活虚拟环境...
call .venv\Scripts\activate.bat

:: ---- 4. 安装依赖 ----
echo [3/5] 检查并安装依赖...
echo   正在升级 pip (使用清华镜像源)...
python -m pip install -q --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
if !ERRORLEVEL! neq 0 (
    echo   [WARN] pip 升级失败，将使用当前版本继续...
)
echo   正在安装项目依赖...
python -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if !ERRORLEVEL! neq 0 (
    echo [WARN] 部分依赖安装失败，尝试继续...
)
echo   依赖安装完成

:: ---- 5. 创建必要目录 ----
if not exist "logs" mkdir logs
if not exist "data" mkdir data

:: ---- 6. 核心导入检查 ----
echo [4/5] 检查核心依赖...
python -c "import fastapi, uvicorn, httpx, yaml, aiosqlite, websockets; print('  核心导入 OK')" 2>nul
if !ERRORLEVEL! neq 0 (
    echo [WARN] 部分核心模块导入失败，尝试继续启动...
)

:: ---- 7. 检查并释放端口 8000 ----
echo.
echo [检查] 正在检查端口 8000 占用情况...
set "PORT_KILLED=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo   发现占用进程 PID: %%p，正在终止...
    taskkill /PID %%p /F >nul 2>&1
    if !ERRORLEVEL! equ 0 (
        set "PORT_KILLED=1"
    ) else (
        echo   [警告] 无法终止 PID %%p，请手动关闭占用 8000 端口的程序后重试。
        pause
        exit /b 1
    )
)
if "!PORT_KILLED!"=="1" (
    echo   端口 8000 已释放，等待 1 秒...
    timeout /t 1 /nobreak >nul
) else (
    echo   端口 8000 空闲，可以启动。
)

:: ---- 8. 启动前端（后台无窗口）★ 本次修复 ----
echo.
echo ==========================================
echo   启动前端开发服务器
echo ==========================================
if not exist "frontend\package.json" goto :skip_frontend

pushd frontend
if not exist "node_modules" (
    echo   安装前端依赖...
    call npm install
)
popd

echo   启动前端 port 3000, 后台无窗口运行...
start /b /D "%AGENT_DIR%frontend" "" cmd /c "npm run dev > %AGENT_DIR%logs\frontend.log 2>&1"
echo   前端已启动: http://localhost:3000  (日志见 logs\frontend.log)
goto :start_agent

:skip_frontend
echo [SKIP] 未找到 frontend\package.json，跳过前端启动

:: ---- 9. 启动 Agent（前台，此窗口即服务本体） ----
:start_agent
echo.
echo ==========================================
echo   启动 Agent 服务 (port 8000)
echo ==========================================
echo.
echo   后端 API:   http://localhost:8000
echo   对话接口:   POST /api/chat  (SSE)
echo   健康检查:   GET  /health
echo   WebSocket:  ws://localhost:8000/ws
echo   前端页面:   http://localhost:3000
echo.
echo   [提示] 本窗口为服务前台，请勿关闭；按 Ctrl+C 正常停止
echo ==========================================
echo.

python -m uvicorn src.main:app --host 0.0.0.0 --port 8000

:: ---- 10. 退出清理（按端口 3000 精确清理前端）★ 本次修复 ----
echo.
echo Agent 已停止，正在清理前端进程...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do (
    taskkill /PID %%p /F /T >nul 2>&1
)
echo 前端进程已清理
pause