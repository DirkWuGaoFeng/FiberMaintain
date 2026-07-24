#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
BUILD_DIR="$PROJECT_DIR/build/src"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"

echo "=========================================="
echo "  光纤维护服务一键启动脚本"
echo "=========================================="

start_service() {
    local service_name=$1
    local service_dir=$2
    local service_exec=$3
    local log_file="$LOG_DIR/${service_name}.log"
    local pid_file="$LOG_DIR/${service_name}.pid"
    
    echo ""
    echo "启动 ${service_name}..."
    
    cd "$service_dir"
    nohup "./${service_exec}" > "$log_file" 2>&1 &
    local pid=$!
    
    echo $pid > "$pid_file"
    echo "  PID: $pid"
    echo "  日志: $log_file"
    
    sleep 1
    
    if kill -0 $pid 2>/dev/null; then
        echo "  [OK] ${service_name} 启动成功"
    else
        echo "  [FAIL] ${service_name} 启动失败"
        cat "$log_file" | tail -20
    fi
}

echo ""
echo "1. 启动 BoardService..."
start_service "board_service" "$BUILD_DIR/board_service" "board_service"

echo ""
echo "2. 启动 TopologyService..."
start_service "topology_service" "$BUILD_DIR/topology_service" "topology_service"

echo ""
echo "3. 启动 PerformanceService..."
start_service "performance_service" "$BUILD_DIR/performance_service" "performance_service"

echo ""
echo "4. 启动 AlarmService..."
start_service "alarm_service" "$BUILD_DIR/alarm_service" "alarm_service"

sleep 2

echo ""
echo "5. 启动 FiberMaintService..."
start_service "fiber_maint_service" "$BUILD_DIR/fiber_maint_service" "fiber_maint_service"

sleep 2

echo ""
echo "6. 启动 API Gateway..."
start_service "api_gateway" "$BUILD_DIR/api_gateway" "api_gateway"

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