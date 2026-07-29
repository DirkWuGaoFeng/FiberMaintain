#!/bin/bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
LOG_DIR="$PROJECT_DIR/logs"

echo "=========================================="
echo "  光纤维护服务一键停止脚本"
echo "=========================================="

# ── 按端口强杀兜底 ──
free_port_hard() {
    local port=$1
    [ -z "$port" ] && return 0
    local pids=""
    pids=$(fuser "${port}/tcp" 2>/dev/null)
    [ -z "${pids// /}" ] && pids=$(fuser "${port}/tcp" 2>&1 1>/dev/null)
    [ -z "${pids// /}" ] && pids=$(lsof -ti "tcp:${port}" 2>/dev/null)
    pids=$(echo "$pids" | tr -cs '0-9' '\n' | grep -E '^[0-9]+$' | sort -u | tr '\n' ' '); pids=${pids% }
    if [ -n "$pids" ]; then
        echo "  [兜底] 强杀占用 :${port} 的残留进程 (PID: ${pids})"
        kill -9 ${pids} 2>/dev/null
    fi
}

stop_service() {
    local service_name=$1 port=$2
    local pid_file="$LOG_DIR/${service_name}.pid"

    echo ""
    echo "停止 ${service_name}..."

    if [ ! -f "$pid_file" ]; then
        echo "  [SKIP] ${service_name} 未运行"
        free_port_hard "$port"      # pid 文件没了但端口可能还被占，兜底
        return
    fi

    local pid=$(cat "$pid_file")

    if ! kill -0 $pid 2>/dev/null; then
        echo "  [SKIP] ${service_name} 进程不存在 (PID: $pid)"
        rm -f "$pid_file"
        free_port_hard "$port"
        return
    fi

    kill $pid
    echo "  发送终止信号给 PID: $pid"

    local wait_count=0
    while kill -0 $pid 2>/dev/null; do
        if [ $wait_count -ge 10 ]; then
            echo "  强制终止 ${service_name}..."
            kill -9 $pid
            break
        fi
        sleep 1
        wait_count=$((wait_count + 1))
    done

    rm -f "$pid_file"
    free_port_hard "$port"          # ★ 确保端口彻底释放
    echo "  [OK] ${service_name} 已停止"
}

echo ""
echo "1. 停止 API Gateway..."
stop_service "api_gateway"          8080
echo ""
echo "2. 停止 FiberMaintService..."
stop_service "fiber_maint_service"  50055
echo ""
echo "3. 停止 AlarmService..."
stop_service "alarm_service"        50054
echo ""
echo "4. 停止 PerformanceService..."
stop_service "performance_service"  50053
echo ""
echo "5. 停止 TopologyService..."
stop_service "topology_service"     50062
echo ""
echo "6. 停止 BoardService..."
stop_service "board_service"        50051
echo ""
echo "=========================================="
echo "  所有服务停止完成！"
echo "=========================================="
echo ""
echo "检查并清理残留进程:"
echo "-------------"
for service in board_service topology_service performance_service alarm_service fiber_maint_service api_gateway; do
    pids=$(pgrep -f "${service}" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "  清理 ${service} 残留进程 (PID: $pids)..."
        kill -9 $pids 2>/dev/null
        echo "✓ ${service}: 已清理"
    else
        echo "✓ ${service}: 已完全停止"
    fi
    rm -f "$LOG_DIR/${service}.pid"
done
# 最后一道保险：把所有监听端口再扫一遍强杀
for p in 8080 50051 50053 50054 50055 50062; do free_port_hard "$p"; done