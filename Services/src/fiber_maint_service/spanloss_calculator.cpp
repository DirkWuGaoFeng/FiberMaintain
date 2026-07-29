/**
 * @file spanloss_calculator.cpp
 * @brief Layer 3 - 衰耗计算器实现
 */

#include "spanloss_calculator.h"
#include "performance.grpc.pb.h"
#include "common/common.h"

namespace fiber_maint {

SpanlossCalculator::SpanlossCalculator(std::shared_ptr<PerfStub> stub)
    : stub_(std::move(stub)) {}

SpanlossResult SpanlossCalculator::calculate(const FiberTopologyInfo& topo) {
    SpanlossResult result;
    result.fiber_id = topo.fiber_id;

    if (!topo.is_inter_ne) {
        result.spanloss = 0.0;
        result.valid = true;
        return result;
    }

    auto pairs = SpanlossTargetBuilder::build(topo);
    if (pairs.empty()) {
        result.error_message = "No spanloss targets";
        return result;
    }

    const auto& pair = pairs[0]; // 单条仅一个 pair

    double src_oop = 0.0, dst_iop = 0.0;

    {
        grpc::ClientContext ctx;
        fiber::performance::GetCurrentPerformanceRequest req;
        req.set_board_id(pair.src_board_id);
        req.set_port_id(pair.src_port_id);
        fiber::performance::GetCurrentPerformanceResponse resp;
        if (stub_->GetCurrentPerformance(&ctx, req, &resp).ok()) {
            src_oop = resp.oop_value();
        }
    }
    {
        grpc::ClientContext ctx;
        fiber::performance::GetCurrentPerformanceRequest req;
        req.set_board_id(pair.dst_board_id);
        req.set_port_id(pair.dst_port_id);
        fiber::performance::GetCurrentPerformanceResponse resp;
        if (stub_->GetCurrentPerformance(&ctx, req, &resp).ok()) {
            dst_iop = resp.iop_value();
        }
    }

    result.spanloss = src_oop - dst_iop;
    result.valid = true;
    return result;
}

std::vector<SpanlossResult> SpanlossCalculator::batch_calculate(
        const std::vector<FiberTopologyInfo>& topos) {
    // Layer 2 批量去重
    auto deduped = SpanlossTargetBuilder::build_batch(topos);

    // 预查询所有去重后的 pair
    struct PairResult {
        double src_oop = 0.0;
        double dst_iop = 0.0;
    };
    std::vector<PairResult> pair_results(deduped.pairs.size());

    for (size_t i = 0; i < deduped.pairs.size(); ++i) {
        const auto& pair = deduped.pairs[i];

        {
            grpc::ClientContext ctx;
            fiber::performance::GetCurrentPerformanceRequest req;
            req.set_board_id(pair.src_board_id);
            req.set_port_id(pair.src_port_id);
            fiber::performance::GetCurrentPerformanceResponse resp;
            if (stub_->GetCurrentPerformance(&ctx, req, &resp).ok()) {
                pair_results[i].src_oop = resp.oop_value();
            }
        }
        {
            grpc::ClientContext ctx;
            fiber::performance::GetCurrentPerformanceRequest req;
            req.set_board_id(pair.dst_board_id);
            req.set_port_id(pair.dst_port_id);
            fiber::performance::GetCurrentPerformanceResponse resp;
            if (stub_->GetCurrentPerformance(&ctx, req, &resp).ok()) {
                pair_results[i].dst_iop = resp.iop_value();
            }
        }
    }

    // 组装结果
    std::vector<SpanlossResult> results;
    results.reserve(deduped.mappings.size());

    for (const auto& [fiber_id, pair_idx] : deduped.mappings) {
        SpanlossResult r;
        r.fiber_id = fiber_id;
        r.spanloss = pair_results[pair_idx].src_oop - pair_results[pair_idx].dst_iop;
        r.valid = true;
        results.push_back(r);
    }

    return results;
}

} // namespace fiber_maint
