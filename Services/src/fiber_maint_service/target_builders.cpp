/**
 * @file target_builders.cpp
 * @brief Layer 2 - 查询目标构建器实现
 *
 * 关键规则（v4.0）：场景2 性能/衰耗仅取主路（Port-2 对端），不取备路（Port-3 对端）。
 */

#include "target_builders.h"
#include <map>

namespace fiber_maint {

// ============================================================
//  AlarmTargetBuilder
// ============================================================

std::vector<AlarmTarget> AlarmTargetBuilder::build(
        const FiberTopologyInfo& topo) {
    std::vector<AlarmTarget> targets;

    if (!topo.is_inter_ne) return targets;

    switch (topo.scene_type) {
    case SceneType::SCENE_1:
        // 场景1：宿端有源盘 Port-1
        targets.push_back({
            topo.dst.board_id, 1, AlarmRole::DST_ACTIVE});
        break;

    case SceneType::SCENE_2:
        switch (topo.scenario_case) {
        case ScenarioCase::CASE_A:
            // Case A：B + A2 双路（Port-2 + Port-3 对端）
            if (topo.primary_peer) {
                targets.push_back({
                    topo.primary_peer->board_id,
                    topo.primary_peer->port_id,
                    AlarmRole::PORT2_PEER});
            }
            if (topo.backup_peer) {
                targets.push_back({
                    topo.backup_peer->board_id,
                    topo.backup_peer->port_id,
                    AlarmRole::PORT3_PEER});
            }
            break;

        case ScenarioCase::CASE_B:
            // Case B：仅 B（Port-2 对端）
            if (topo.primary_peer) {
                targets.push_back({
                    topo.primary_peer->board_id,
                    topo.primary_peer->port_id,
                    AlarmRole::PORT2_PEER});
            }
            break;

        case ScenarioCase::CASE_C:
            // Case C：无告警目标，固定 GREEN
            break;

        default:
            break;
        }
        break;
    }

    return targets;
}

// ============================================================
//  PerfTargetBuilder
// ============================================================

std::vector<PerfTarget> PerfTargetBuilder::build(
        const FiberTopologyInfo& topo) {
    std::vector<PerfTarget> targets;

    if (!topo.is_inter_ne) return targets;

    switch (topo.scene_type) {
    case SceneType::SCENE_1:
        // 场景1：src OOP + dst IOP
        targets.push_back({topo.src.board_id, 1, true});
        targets.push_back({topo.dst.board_id, 1, false});
        break;

    case SceneType::SCENE_2:
        // v4.0 关键变更：场景2 仅取主路（Port-2 对端），不取备路
        switch (topo.scenario_case) {
        case ScenarioCase::CASE_A:
        case ScenarioCase::CASE_B:
            // src OOP + primary_peer (Board-B) IOP
            targets.push_back({topo.src.board_id, 1, true});
            if (topo.primary_peer) {
                targets.push_back({
                    topo.primary_peer->board_id,
                    topo.primary_peer->port_id,
                    false});
            }
            break;

        case ScenarioCase::CASE_C:
            // 无性能目标
            break;

        default:
            break;
        }
        break;
    }

    return targets;
}

DeduplicatedPerfTargets PerfTargetBuilder::build_batch(
        const std::vector<FiberTopologyInfo>& topos) {
    DeduplicatedPerfTargets result;

    // 去重键：(board_id, port_id, is_src)
    struct DedupeKey {
        int32_t board_id;
        int32_t port_id;
        bool    is_src;
        bool operator<(const DedupeKey& o) const {
            if (board_id != o.board_id) return board_id < o.board_id;
            if (port_id != o.port_id) return port_id < o.port_id;
            return is_src < o.is_src;
        }
    };

    std::map<DedupeKey, size_t> seen;

    auto get_or_add = [&](int32_t board_id, int32_t port_id, bool is_src) -> size_t {
        DedupeKey key{board_id, port_id, is_src};
        auto it = seen.find(key);
        if (it != seen.end()) return it->second;
        size_t idx = result.targets.size();
        result.targets.push_back({board_id, port_id, is_src});
        seen[key] = idx;
        return idx;
    };

    for (const auto& topo : topos) {
        if (!topo.is_inter_ne) continue;

        DeduplicatedPerfTargets::FiberMapping mapping;
        mapping.fiber_id = topo.fiber_id;

        switch (topo.scene_type) {
        case SceneType::SCENE_1:
            mapping.src_idx = get_or_add(topo.src.board_id, 1, true);
            mapping.dst_idx = get_or_add(topo.dst.board_id, 1, false);
            result.mappings.push_back(mapping);
            break;

        case SceneType::SCENE_2:
            if (topo.scenario_case == ScenarioCase::CASE_C) break;
            mapping.src_idx = get_or_add(topo.src.board_id, 1, true);
            if (topo.primary_peer) {
                mapping.dst_idx = get_or_add(
                    topo.primary_peer->board_id,
                    topo.primary_peer->port_id, false);
            } else {
                mapping.dst_idx = mapping.src_idx; // fallback
            }
            result.mappings.push_back(mapping);
            break;
        }
    }

    return result;
}

// ============================================================
//  SpanlossTargetBuilder
// ============================================================

std::vector<SpanlossPair> SpanlossTargetBuilder::build(
        const FiberTopologyInfo& topo) {
    std::vector<SpanlossPair> pairs;

    if (!topo.is_inter_ne) return pairs;

    switch (topo.scene_type) {
    case SceneType::SCENE_1:
        pairs.push_back({
            topo.src.board_id, 1,
            topo.dst.board_id, 1});
        break;

    case SceneType::SCENE_2:
        // v4.0：场景2 仅主路
        if (topo.scenario_case != ScenarioCase::CASE_C && topo.primary_peer) {
            pairs.push_back({
                topo.src.board_id, 1,
                topo.primary_peer->board_id,
                topo.primary_peer->port_id});
        }
        break;
    }

    return pairs;
}

DeduplicatedSpanlossPairs SpanlossTargetBuilder::build_batch(
        const std::vector<FiberTopologyInfo>& topos) {
    DeduplicatedSpanlossPairs result;

    struct DedupeKey {
        int32_t src_board, src_port, dst_board, dst_port;
        bool operator<(const DedupeKey& o) const {
            if (src_board != o.src_board) return src_board < o.src_board;
            if (src_port != o.src_port) return src_port < o.src_port;
            if (dst_board != o.dst_board) return dst_board < o.dst_board;
            return dst_port < o.dst_port;
        }
    };

    std::map<DedupeKey, size_t> seen;

    for (const auto& topo : topos) {
        if (!topo.is_inter_ne) continue;

        int32_t dst_board = topo.dst.board_id;
        int32_t dst_port  = 1;

        if (topo.scene_type == SceneType::SCENE_2) {
            if (topo.scenario_case == ScenarioCase::CASE_C) continue;
            if (topo.primary_peer) {
                dst_board = topo.primary_peer->board_id;
                dst_port  = topo.primary_peer->port_id;
            } else {
                continue;
            }
        }

        DedupeKey key{topo.src.board_id, 1, dst_board, dst_port};
        auto it = seen.find(key);
        size_t idx;
        if (it != seen.end()) {
            idx = it->second;
        } else {
            idx = result.pairs.size();
            result.pairs.push_back({topo.src.board_id, 1, dst_board, dst_port});
            seen[key] = idx;
        }
        result.mappings.push_back({topo.fiber_id, idx});
    }

    return result;
}

} // namespace fiber_maint
