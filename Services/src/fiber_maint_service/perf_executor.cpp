/**
 * @file perf_executor.cpp
 * @brief Layer 3 - 性能查询执行器实现
 */

#include "perf_executor.h"
#include "performance.grpc.pb.h"
#include "common/common.h"

namespace fiber_maint {

PerfQueryExecutor::PerfQueryExecutor(std::shared_ptr<PerfStub> stub)
    : stub_(std::move(stub)) {}

double PerfQueryExecutor::query_oop(int32_t board_id, int32_t port_id) {
    grpc::ClientContext ctx;
    fiber::performance::GetCurrentPerformanceRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    fiber::performance::GetCurrentPerformanceResponse resp;

    auto status = stub_->GetCurrentPerformance(&ctx, req, &resp);
    return status.ok() ? resp.oop_value() : 0.0;
}

double PerfQueryExecutor::query_iop(int32_t board_id, int32_t port_id) {
    grpc::ClientContext ctx;
    fiber::performance::GetCurrentPerformanceRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    fiber::performance::GetCurrentPerformanceResponse resp;

    auto status = stub_->GetCurrentPerformance(&ctx, req, &resp);
    return status.ok() ? resp.iop_value() : 0.0;
}

PerfResult PerfQueryExecutor::execute(const FiberTopologyInfo& topo) {
    PerfResult result;
    result.fiber_id = topo.fiber_id;

    if (!topo.is_inter_ne) {
        result.error_message = "Only inter-NE fibers supported";
        return result;
    }

    auto targets = PerfTargetBuilder::build(topo);
    if (targets.empty()) {
        result.error_message = "No performance targets";
        return result;
    }

    for (const auto& target : targets) {
        if (target.is_src) {
            result.src_oop = query_oop(target.board_id, target.port_id);
        } else {
            result.dst_iop = query_iop(target.board_id, target.port_id);
        }
    }

    result.valid = true;
    return result;
}

std::vector<PerfResult> PerfQueryExecutor::batch_execute(
        const std::vector<FiberTopologyInfo>& topos) {
    // Layer 2 批量去重
    auto deduped = PerfTargetBuilder::build_batch(topos);

    // 预查询所有去重后的目标
    struct CachedValue {
        double oop = 0.0;
        double iop = 0.0;
        bool   queried_oop = false;
        bool   queried_iop = false;
    };
    std::vector<CachedValue> cache(deduped.targets.size());

    for (size_t i = 0; i < deduped.targets.size(); ++i) {
        const auto& t = deduped.targets[i];
        grpc::ClientContext ctx;
        fiber::performance::GetCurrentPerformanceRequest req;
        req.set_board_id(t.board_id);
        req.set_port_id(t.port_id);
        fiber::performance::GetCurrentPerformanceResponse resp;

        if (stub_->GetCurrentPerformance(&ctx, req, &resp).ok()) {
            cache[i].oop = resp.oop_value();
            cache[i].iop = resp.iop_value();
            cache[i].queried_oop = true;
            cache[i].queried_iop = true;
        }
    }

    // 组装结果
    std::vector<PerfResult> results;
    results.reserve(deduped.mappings.size());

    for (const auto& mapping : deduped.mappings) {
        PerfResult r;
        r.fiber_id = mapping.fiber_id;
        r.src_oop  = cache[mapping.src_idx].oop;
        r.dst_iop  = cache[mapping.dst_idx].iop;
        r.valid    = cache[mapping.src_idx].queried_oop ||
                     cache[mapping.dst_idx].queried_iop;
        results.push_back(r);
    }

    return results;
}

} // namespace fiber_maint
