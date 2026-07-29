#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
BUILD_DIR="$PROJECT_DIR/build/src"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "=========================================="
echo "  光纤维护服务一键启动脚本"
echo "=========================================="

if ! command -v fuser >/dev/null 2>&1 && ! command -v lsof >/dev/null 2>&1; then
    echo "[WARN] 未安装 fuser/lsof，端口预清理将失效。建议: sudo apt install -y psmisc lsof"
fi

# ── 释放指定 TCP 端口（fuser 的 pid 在 stderr，需双捕获；lsof 兜底） ──
ensure_port_free() {
    local port=$1
    [ -z "$port" ] && return 0
    local pids=""
    pids=$(fuser "${port}/tcp" 2>/dev/null)
    [ -z "${pids// /}" ] && pids=$(fuser "${port}/tcp" 2>&1 1>/dev/null)
    [ -z "${pids// /}" ] && pids=$(lsof -ti "tcp:${port}" 2>/dev/null)
    pids=$(echo "$pids" | tr -cs '0-9' '\n' | grep -E '^[0-9]+$' | sort -u | tr '\n' ' '); pids=${pids% }
    if [ -n "$pids" ]; then
        echo "  [端口清理] :${port} 被占用 (PID: ${pids})，释放中..."
        kill ${pids} 2>/dev/null; sleep 1; kill -9 ${pids} 2>/dev/null
        local i=0
        while [ $i -lt 8 ]; do
            local s=""
            s=$(fuser "${port}/tcp" 2>/dev/null); [ -z "${s// /}" ] && s=$(fuser "${port}/tcp" 2>&1 1>/dev/null)
            [ -z "${s// /}" ] && s=$(lsof -ti "tcp:${port}" 2>/dev/null)
            [ -z "${s// /}" ] && break
            sleep 1; i=$((i+1))
        done
        [ $i -ge 8 ] && echo "  [警告] :${port} 仍无法释放，该服务可能启动失败"
    fi
}

start_service() {
    local service_name=$1 service_dir=$2 service_exec=$3 port=$4
    local log_file="$LOG_DIR/${service_name}.log"
    local pid_file="$LOG_DIR/${service_name}.pid"

    echo ""
    echo "启动 ${service_name}..."

    # 防重入：pid 文件指向的进程还活着，就别重复拉
    if [ -f "$pid_file" ]; then
        local old=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$old" ] && kill -0 "$old" 2>/dev/null; then
            echo "  [SKIP] ${service_name} 已在运行 (PID: $old)。如需重启请先执行 stop_services.sh"
            return
        fi
    fi

    ensure_port_free "$port"          # ★ 启动前先腾出端口

    cd "$PROJECT_DIR"
    nohup "$service_dir/${service_exec}" > "$log_file" 2>&1 &
    local pid=$!
    echo $pid > "$pid_file"
    echo "  PID: $pid"
    echo "  日志: $log_file"

    sleep 1

    if ! kill -0 $pid 2>/dev/null; then
        echo "  [FAIL] ${service_name} 启动失败（进程已退出）"
        tail -20 "$log_file"
        return
    fi
    # ★ 进程在 ≠ 端口起来了；用日志致命关键字复核
    if grep -qiE "Failed to start|Address already in use|bind failed|EADDRINUSE|terminate called|Segmentation fault" "$log_file"; then
        echo "  [WARN] ${service_name} 进程存活但日志含致命错误，请检查："
        tail -20 "$log_file"
    else
        echo "  [OK] ${service_name} 启动成功"
    fi
}

echo ""
echo "1. 启动 BoardService..."
start_service "board_service"        "$BUILD_DIR/board_service"        "board_service"        50051
echo ""
echo "2. 启动 TopologyService..."
start_service "topology_service"     "$BUILD_DIR/topology_service"     "topology_service"     50062
echo ""
echo "3. 启动 PerformanceService..."
start_service "performance_service"  "$BUILD_DIR/performance_service"  "performance_service"  50053
echo ""
echo "4. 启动 AlarmService..."
start_service "alarm_service"        "$BUILD_DIR/alarm_service"        "alarm_service"        50054
sleep 2
echo ""
echo "5. 启动 FiberMaintService..."
start_service "fiber_maint_service"  "$BUILD_DIR/fiber_maint_service"  "fiber_maint_service"  50055
sleep 2
echo ""
echo "6. 启动 API Gateway..."
start_service "api_gateway"          "$BUILD_DIR/api_gateway"          "api_gateway"          8080
echo ""
echo "=========================================="
echo "  所有服务启动完成！"
echo "=========================================="
echo ""
echo "服务状态:"
echo "----------"
for service in board_service topology_service performance_service alarm_service fiber_maint_service api_gateway; do
    pid_file="$LOG_DIR/${service}.pid"
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        if kill -0 $pid 2>/dev/null; then
            echo "✓ ${service}: 运行中 (PID: $pid)"
        else
            echo "✗ ${service}: 已停止"
        fi
    else
        echo "? ${service}: 未启动"
    fi
done
echo ""
echo "日志目录: $LOG_DIR"
echo ""
echo "=========================================="
echo "  模拟器使用说明"
echo "=========================================="
echo "场景模拟器 (创建测试数据):"
echo "  cd /mnt/e/Work/FiberMaintain/Services/build/src/simulators"
echo "  ./scene_simulator"
echo ""
echo "告警模拟器 (持续上报告警):"
echo "  cd /mnt/e/Work/FiberMaintain/Services/build/src/simulators"
echo "  ./alarm_simulator [BoardService地址] [AlarmService地址] [上报间隔ms]"
echo "  示例: ./alarm_simulator localhost:50051 localhost:50054 1000"
echo ""
echo "性能模拟器 (持续上报性能):"
echo "  cd /mnt/e/Work/FiberMaintain/Services/build/src/simulators"
echo "  ./performance_simulator [BoardService地址] [PerformanceService地址] [上报间隔ms]"
echo "  示例: ./performance_simulator localhost:50051 localhost:50053 5000"