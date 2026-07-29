#pragma once

/**
 * @file perf_executor.h
 * @brief Layer 3 - 性能查询执行器
 *
 * 接收 Layer 2 的 PerfTarget，通过 gRPC 执行性能查询。
 * 批量模式下自动去重 + 单次 RPC 调用。
 */

#include "types.h"
#include "target_builders.h"
#include "performance.grpc.pb.h"
#include <memory>

namespace fiber_maint {

class PerfQueryExecutor {
public:
    using PerfStub = fiber::performance::PerformanceService::Stub;

    explicit PerfQueryExecutor(std::shared_ptr<PerfStub> stub);

    /// 单条查询（L1 topo → L2 targets → gRPC）
    PerfResult execute(const FiberTopologyInfo& topo);

    /// 批量查询（去重后单次 RPC 调用）
    std::vector<PerfResult> batch_execute(
        const std::vector<FiberTopologyInfo>& topos);

private:
    /// 查询单个板卡端口的光功率值
    double query_oop(int32_t board_id, int32_t port_id);
    double query_iop(int32_t board_id, int32_t port_id);

    std::shared_ptr<PerfStub> stub_;
};

} // namespace fiber_maint
