#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
LOG_DIR="$PROJECT_DIR/logs"

echo "=========================================="
echo "  光纤维护服务一键停止脚本"
echo "=========================================="

stop_service() {
    local service_name=$1
    local pid_file="$LOG_DIR/${service_name}.pid"
    
    echo ""
    echo "停止 ${service_name}..."
    
    if [ ! -f "$pid_file" ]; then
        echo "  [SKIP] ${service_name} 未运行"
        return
    fi
    
    local pid=$(cat "$pid_file")
    
    if ! kill -0 $pid 2>/dev/null; then
        echo "  [SKIP] ${service_name} 进程不存在 (PID: $pid)"
        rm -f "$pid_file"
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
    echo "  [OK] ${service_name} 已停止"
}

echo ""
echo "1. 停止 API Gateway..."
stop_service "api_gateway"

echo ""
echo "2. 停止 FiberMaintService..."
stop_service "fiber_maint_service"

echo ""
echo "3. 停止 AlarmService..."
stop_service "alarm_service"

echo ""
echo "4. 停止 PerformanceService..."
stop_service "performance_service"

echo ""
echo "5. 停止 TopologyService..."
stop_service "topology_service"

echo ""
echo "6. 停止 BoardService..."
stop_service "board_service"

echo ""
echo "=========================================="
echo "  所有服务停止完成！"
echo "=========================================="
echo ""
echo "检查残留进程:"
echo "-------------"
for service in board_service topology_service performance_service alarm_service fiber_maint_service api_gateway; do
    pid=$(pgrep -f "./${service}" 2>/dev/null)
    if [ -n "$pid" ]; then
        echo "✗ ${service}: 仍有残留进程 (PID: $pid)"
    else
        echo "✓ ${service}: 已完全停止"
    fi
done