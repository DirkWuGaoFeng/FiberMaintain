#!/bin/bash
# ============================================================
# FiberMaintService E2E 自动化集成测试脚本
#
# 流程: 编译 → 启动服务 → 模拟器注入数据 → 执行测试 → 生成报告 → 清理
#
# 用法:
#   ./run_e2e_test.sh [选项]
#
# 选项:
#   --skip-build       跳过编译阶段
#   --keep-services    测试完成后不停止服务
#   --skip-simulators  跳过模拟器数据注入
#   -h, --help         显示帮助
# ============================================================

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(dirname "$SCRIPT_DIR")
BUILD_DIR="$PROJECT_DIR/build"
LOG_DIR="$PROJECT_DIR/logs"
TEST_LOG="$LOG_DIR/e2e_test_output.log"
REPORT_FILE="$PROJECT_DIR/tests/test_report.md"
SIMULATOR_DIR="$BUILD_DIR/src/simulators"
TEST_BIN="$BUILD_DIR/tests/fiber_maint_e2e_test"
ALL_SVC_TEST_BIN="$BUILD_DIR/tests/all_services_test"
ALL_SVC_LOG="$LOG_DIR/all_services_test_output.log"

# 参数解析
SKIP_BUILD=false
KEEP_SERVICES=false
SKIP_SIMULATORS=false

for arg in "$@"; do
    case "$arg" in
        --skip-build)      SKIP_BUILD=true ;;
        --keep-services)   KEEP_SERVICES=true ;;
        --skip-simulators) SKIP_SIMULATORS=true ;;
        -h|--help)
            echo "用法: $0 [--skip-build] [--keep-services] [--skip-simulators]"
            exit 0 ;;
        *) echo "[WARN] 未知参数: $arg" ;;
    esac
done

PERF_SIM_PID=""
TEST_START_TIME=$(date '+%Y-%m-%d %H:%M:%S')

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# 清理函数
cleanup() {
    if [ -n "$PERF_SIM_PID" ] && kill -0 "$PERF_SIM_PID" 2>/dev/null; then
        log_info "停止 performance_simulator (PID: $PERF_SIM_PID)..."
        kill "$PERF_SIM_PID" 2>/dev/null || true
        wait "$PERF_SIM_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ============================================================
# Phase 1: 编译
# ============================================================
phase_build() {
    log_info "========== Phase 1: 编译 =========="
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"
    cmake .. -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -5
    make -j"$(nproc)" 2>&1 | tail -20
    if [ ! -f "$TEST_BIN" ]; then
        log_error "编译产物 $TEST_BIN 不存在，编译可能失败"
        exit 1
    fi
    log_info "编译完成"
}

# ============================================================
# Phase 2: 启动服务
# ============================================================
wait_port_ready() {
    local port=$1 name=$2 max_wait=${3:-30}
    local i=0
    while [ $i -lt $max_wait ]; do
        if timeout 2 bash -c "echo > /dev/tcp/localhost/$port" 2>/dev/null; then
            log_info "$name (port $port) 就绪"
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done
    log_error "$name (port $port) 在 ${max_wait}s 内未就绪"
    return 1
}

phase_start_services() {
    log_info "========== Phase 2: 启动服务 =========="
    bash "$SCRIPT_DIR/start_services.sh"

    log_info "等待服务就绪..."
    wait_port_ready 50051 "BoardService"
    wait_port_ready 50062 "TopologyService"
    wait_port_ready 50053 "PerformanceService"
    wait_port_ready 50054 "AlarmService"
    wait_port_ready 50055 "FiberMaintService"
    log_info "所有服务已就绪"
}

# ============================================================
# Phase 3: 模拟器注入测试数据
# ============================================================
phase_simulators() {
    log_info "========== Phase 3: 模拟器注入数据 =========="

    if [ ! -f "$SIMULATOR_DIR/scene_simulator" ]; then
        log_warn "scene_simulator 不存在，跳过模拟器阶段"
        return 0
    fi

    # 场景模拟器：创建 200 条拓扑
    log_info "运行 scene_simulator (创建拓扑)..."
    "$SIMULATOR_DIR/scene_simulator" localhost:50051 localhost:50062 2>&1 | tail -10
    log_info "scene_simulator 完成"

    # 性能模拟器：后台运行
    if [ -f "$SIMULATOR_DIR/performance_simulator" ]; then
        log_info "后台启动 performance_simulator (间隔 2s)..."
        "$SIMULATOR_DIR/performance_simulator" localhost:50051 localhost:50053 2000 \
            > "$LOG_DIR/performance_simulator.log" 2>&1 &
        PERF_SIM_PID=$!
        log_info "performance_simulator PID: $PERF_SIM_PID"

        log_info "等待 5s 让性能数据积累..."
        sleep 5
    fi
}

# ============================================================
# Phase 4: 执行 E2E 测试
# ============================================================
TEST_EXIT_CODE=0

phase_run_test() {
    log_info "========== Phase 4: 执行 E2E 测试 =========="
    mkdir -p "$LOG_DIR"

    set +e
    "$TEST_BIN" 2>&1 | tee "$TEST_LOG"
    TEST_EXIT_CODE=${PIPESTATUS[0]}
    set -e

    if [ $TEST_EXIT_CODE -eq 0 ]; then
        log_info "E2E 测试全部通过 (exit code: 0)"
    else
        log_warn "E2E 测试存在失败 (exit code: $TEST_EXIT_CODE)"
    fi

    # 全服务功能测试
    if [ -f "$ALL_SVC_TEST_BIN" ]; then
        log_info "执行全服务功能测试..."
        set +e
        "$ALL_SVC_TEST_BIN" 2>&1 | tee "$ALL_SVC_LOG"
        local svc_exit=${PIPESTATUS[0]}
        set -e
        if [ $svc_exit -eq 0 ]; then
            log_info "全服务测试全部通过"
        else
            log_warn "全服务测试存在失败 (exit code: $svc_exit)"
        fi
        # 合并退出码
        [ $svc_exit -ne 0 ] && TEST_EXIT_CODE=1
    fi
}

# ============================================================
# Phase 5: 生成测试报告
# ============================================================
phase_generate_report() {
    log_info "========== Phase 5: 生成测试报告 =========="

    local test_end_time
    test_end_time=$(date '+%Y-%m-%d %H:%M:%S')

    # 解析统计数据
    local total_pass total_fail total_cases pass_rate
    total_pass=$(grep -c '\[PASS\]' "$TEST_LOG" 2>/dev/null || echo "0")
    total_fail=$(grep -c '\[FAIL\]' "$TEST_LOG" 2>/dev/null || echo "0")
    total_cases=$((total_pass + total_fail))

    if [ $total_cases -gt 0 ]; then
        pass_rate=$(awk "BEGIN {printf \"%.1f\", $total_pass * 100.0 / $total_cases}")
    else
        pass_rate="0.0"
    fi

    # 提取服务版本
    local version
    version=$(grep -oP 'version: \K[^)]+' "$TEST_LOG" 2>/dev/null || echo "unknown")

    # 按组解析（通过测试输出中的组标题行）
    local group_stats=""
    local current_group=""
    local group_pass=0
    local group_fail=0

    while IFS= read -r line; do
        # 检测组标题行（以 "=== Group" 或类似格式开头）
        if echo "$line" | grep -qE '^\s*(===|---)\s*(Group|测试组)'; then
            # 输出上一组统计
            if [ -n "$current_group" ]; then
                local g_total=$((group_pass + group_fail))
                local g_status="PASS"
                [ $group_fail -gt 0 ] && g_status="**FAIL**"
                group_stats="${group_stats}| ${current_group} | ${group_pass}/${g_total} | ${group_fail} | ${g_status} |\n"
            fi
            current_group=$(echo "$line" | sed 's/^[= -]*//' | sed 's/[= -]*$//')
            group_pass=0
            group_fail=0
        elif echo "$line" | grep -q '\[PASS\]'; then
            group_pass=$((group_pass + 1))
        elif echo "$line" | grep -q '\[FAIL\]'; then
            group_fail=$((group_fail + 1))
        fi
    done < "$TEST_LOG"

    # 最后一组
    if [ -n "$current_group" ]; then
        local g_total=$((group_pass + group_fail))
        local g_status="PASS"
        [ $group_fail -gt 0 ] && g_status="**FAIL**"
        group_stats="${group_stats}| ${current_group} | ${group_pass}/${g_total} | ${group_fail} | ${g_status} |\n"
    fi

    # 失败详情
    local fail_details
    fail_details=$(grep '\[FAIL\]' "$TEST_LOG" 2>/dev/null | sed 's/^/- /' || echo "- 无")

    # 模拟器信息
    local sim_info="未运行"
    if [ "$SKIP_SIMULATORS" = false ]; then
        local scene_count
        scene_count=$(grep -oP '总计: \K[0-9]+' "$LOG_DIR/performance_simulator.log" 2>/dev/null || echo "N/A")
        sim_info="scene_simulator: 200 条拓扑; performance_simulator: 后台运行"
    fi

    # 总体状态
    local overall_status="PASS"
    [ $total_fail -gt 0 ] && overall_status="FAIL"

    # 写入报告
    cat > "$REPORT_FILE" << EOF
# FiberMaintService E2E 测试报告

## 基本信息

| 项目 | 值 |
|------|-----|
| 测试时间 | ${TEST_START_TIME} ~ ${test_end_time} |
| 测试环境 | WSL / localhost |
| 服务版本 | ${version} |
| 总体结果 | **${overall_status}** |

## 总览

| 指标 | 值 |
|------|-----|
| 总用例数 | ${total_cases} |
| 通过 | ${total_pass} |
| 失败 | ${total_fail} |
| 通过率 | ${pass_rate}% |

## 分组结果

| 测试组 | 通过 | 失败 | 状态 |
|--------|------|------|------|
$(echo -e "$group_stats")

## 失败详情

${fail_details}

## 模拟器数据注入

- 状态: ${sim_info}
- 说明: E2E 测试自建独立拓扑（唯一 ID），模拟器提供背景负载数据

## 测试日志

完整日志: \`Services/logs/e2e_test_output.log\`

---
*报告由 run_e2e_test.sh 自动生成*
EOF

    log_info "测试报告已生成: $REPORT_FILE"
}

# ============================================================
# Phase 6: 清理
# ============================================================
phase_cleanup() {
    log_info "========== Phase 6: 清理 =========="

    # performance_simulator 由 trap cleanup 处理
    if [ -n "$PERF_SIM_PID" ] && kill -0 "$PERF_SIM_PID" 2>/dev/null; then
        kill "$PERF_SIM_PID" 2>/dev/null || true
        PERF_SIM_PID=""
    fi

    if [ "$KEEP_SERVICES" = false ]; then
        log_info "停止所有服务..."
        bash "$SCRIPT_DIR/stop_services.sh" 2>/dev/null || true
    else
        log_info "保留服务运行 (--keep-services)"
    fi
}

# ============================================================
# 主流程
# ============================================================
main() {
    echo ""
    echo "========================================================"
    echo "  FiberMaintService E2E 自动化集成测试"
    echo "  时间: $TEST_START_TIME"
    echo "========================================================"
    echo ""

    [ "$SKIP_BUILD" = false ] && phase_build
    phase_start_services
    [ "$SKIP_SIMULATORS" = false ] && phase_simulators
    phase_run_test
    phase_generate_report
    phase_cleanup

    echo ""
    echo "========================================================"
    if [ $TEST_EXIT_CODE -eq 0 ]; then
        log_info "测试完成: 全部通过"
    else
        log_warn "测试完成: 存在失败用例，请查看报告 $REPORT_FILE"
    fi
    echo "========================================================"
    echo ""

    exit $TEST_EXIT_CODE
}

main
