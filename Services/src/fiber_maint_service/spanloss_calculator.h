#pragma once

/**
 * @file spanloss_calculator.h
 * @brief Layer 3 - 衰耗计算器
 *
 * 接收 Layer 2 的 SpanlossPair，通过 gRPC 查询光功率并计算衰耗。
 * spanloss = src_oop - dst_iop
 */

#include "types.h"
#include "target_builders.h"
#include "performance.grpc.pb.h"
#include <memory>

namespace fiber_maint {

class SpanlossCalculator {
public:
    using PerfStub = fiber::performance::PerformanceService::Stub;

    explicit SpanlossCalculator(std::shared_ptr<PerfStub> stub);

    /// 单条计算
    SpanlossResult calculate(const FiberTopologyInfo& topo);

    /// 批量计算（去重后减少 RPC 调用）
    std::vector<SpanlossResult> batch_calculate(
        const std::vector<FiberTopologyInfo>& topos);

private:
    std::shared_ptr<PerfStub> stub_;
};

} // namespace fiber_maint
