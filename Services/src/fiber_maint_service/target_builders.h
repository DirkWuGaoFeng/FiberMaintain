#pragma once

/**
 * @file target_builders.h
 * @brief Layer 2 - 查询目标构建器族
 *
 * 将 Layer 1 FiberTopologyInfo 转换为 Layer 3 所需的查询目标列表。
 * - AlarmTargetBuilder:    告警查询目标
 * - PerfTargetBuilder:     性能查询目标（v4.0 场景2仅主路）
 * - SpanlossTargetBuilder: 衰耗查询对（v4.0 场景2仅主路）
 */

#include "types.h"
#include <unordered_set>

namespace fiber_maint {

// ============================================================
//  AlarmTargetBuilder
// ============================================================

class AlarmTargetBuilder {
public:
    /// 根据拓扑构建告警查询目标列表
    static std::vector<AlarmTarget> build(const FiberTopologyInfo& topo);
};

// ============================================================
//  PerfTargetBuilder
// ============================================================

struct DeduplicatedPerfTargets {
    /// 去重后的查询目标（board_id, port_id → 查询一次）
    std::vector<PerfTarget> targets;
    /// fiber_id → 目标索引映射（src 索引, dst 索引）
    struct FiberMapping {
        int32_t fiber_id;
        size_t  src_idx;  ///< targets 中 OOP 目标索引
        size_t  dst_idx;  ///< targets 中 IOP 目标索引
    };
    std::vector<FiberMapping> mappings;
};

class PerfTargetBuilder {
public:
    /// 单条构建
    static std::vector<PerfTarget> build(const FiberTopologyInfo& topo);

    /// 批量构建（去重 + 单次 RPC 优化）
    static DeduplicatedPerfTargets build_batch(
        const std::vector<FiberTopologyInfo>& topos);
};

// ============================================================
//  SpanlossTargetBuilder
// ============================================================

struct DeduplicatedSpanlossPairs {
    std::vector<SpanlossPair> pairs;
    /// fiber_id → pairs 中的索引
    std::vector<std::pair<int32_t, size_t>> mappings;
};

class SpanlossTargetBuilder {
public:
    /// 单条构建
    static std::vector<SpanlossPair> build(const FiberTopologyInfo& topo);

    /// 批量构建（去重）
    static DeduplicatedSpanlossPairs build_batch(
        const std::vector<FiberTopologyInfo>& topos);
};

} // namespace fiber_maint
