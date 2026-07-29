/**
 * @file fiber_topology_resolver.cpp
 * @brief Layer 1 - 光纤拓扑解析器实现
 */

#include "fiber_topology_resolver.h"
#include "fiber_maint_service_impl.h"   // FiberCacheEntry
#include "common/common.h"

namespace fiber_maint {

void FiberTopologyResolver::bind(
        const FiberByIdMap* fiber_by_id,
        const FiberByPortMap* fiber_by_port,
        std::shared_mutex* cache_mutex) {
    fiber_by_id_   = fiber_by_id;
    fiber_by_port_ = fiber_by_port;
    cache_mutex_   = cache_mutex;
}

// ─────────────────────── resolve ───────────────────────

FiberTopologyInfo FiberTopologyResolver::resolve(int32_t fiber_id) const {
    FiberTopologyInfo info;
    info.fiber_id = fiber_id;

    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) {
        return info;
    }

    std::shared_lock<std::shared_mutex> lock(*cache_mutex_);

    auto it = fiber_by_id_->find(fiber_id);
    if (it == fiber_by_id_->end()) {
        info.is_inter_ne = false;
        return info;
    }

    const auto& entry = it->second;
    info.is_inter_ne = entry.is_inter_ne;
    info.src = {entry.src_board_id, static_cast<int32_t>(entry.src_port_id)};
    info.dst = {entry.dst_board_id, static_cast<int32_t>(entry.dst_port_id)};

    if (entry.is_inter_ne) {
        resolve_scene(info, entry);
    }

    return info;
}

std::vector<FiberTopologyInfo> FiberTopologyResolver::resolve_batch(
        const std::vector<int32_t>& fiber_ids) const {
    std::vector<FiberTopologyInfo> results;
    results.reserve(fiber_ids.size());
    for (int32_t fid : fiber_ids) {
        results.push_back(resolve(fid));
    }
    return results;
}

// ──────────────────── 端口查找 ────────────────────

std::vector<int32_t> FiberTopologyResolver::get_inter_ne_fibers_by_port(
        PortKey port) const {
    std::vector<int32_t> result;
    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) return result;

    std::shared_lock<std::shared_mutex> lock(*cache_mutex_);

    auto range = fiber_by_port_->equal_range(port);
    for (auto it = range.first; it != range.second; ++it) {
        auto f_it = fiber_by_id_->find(it->second);
        if (f_it != fiber_by_id_->end() && f_it->second.is_inter_ne) {
            result.push_back(it->second);
        }
    }
    return result;
}

std::optional<int32_t> FiberTopologyResolver::get_intra_ne_fiber_by_port(
        PortKey port) const {
    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) return std::nullopt;

    std::shared_lock<std::shared_mutex> lock(*cache_mutex_);

    auto range = fiber_by_port_->equal_range(port);
    for (auto it = range.first; it != range.second; ++it) {
        auto f_it = fiber_by_id_->find(it->second);
        if (f_it != fiber_by_id_->end() && !f_it->second.is_inter_ne) {
            return it->second;
        }
    }
    return std::nullopt;
}

// ──────────────────── 单盘分类 ────────────────────

BoardType FiberTopologyResolver::classify_board(int32_t board_id) const {
    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) {
        return BoardType::ACTIVE;
    }

    std::shared_lock<std::shared_mutex> lock(*cache_mutex_);

    // 检查 Port-2 或 Port-3 是否有网元内连纤 → 有则为无源盘
    for (int32_t port : {2, 3}) {
        PortKey pk{board_id, port};
        auto range = fiber_by_port_->equal_range(pk);
        for (auto it = range.first; it != range.second; ++it) {
            auto f_it = fiber_by_id_->find(it->second);
            if (f_it != fiber_by_id_->end() && !f_it->second.is_inter_ne) {
                return BoardType::PASSIVE;
            }
        }
    }
    return BoardType::ACTIVE;
}

std::vector<PeerInfo> FiberTopologyResolver::find_peers_on_passive_board(
        int32_t board_id, int32_t exclude_port) const {
    std::vector<PeerInfo> peers;
    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) return peers;

    std::shared_lock<std::shared_mutex> lock(*cache_mutex_);

    for (int32_t port : {2, 3}) {
        if (port == exclude_port) continue;

        PortKey pk{board_id, port};
        auto range = fiber_by_port_->equal_range(pk);
        for (auto it = range.first; it != range.second; ++it) {
            auto f_it = fiber_by_id_->find(it->second);
            if (f_it == fiber_by_id_->end()) continue;
            if (f_it->second.is_inter_ne) continue;

            const auto& entry = f_it->second;
            int32_t peer_board = (entry.src_board_id == board_id)
                ? entry.dst_board_id : entry.src_board_id;

            PeerInfo pi;
            pi.board_id = peer_board;
            pi.port_id  = 1;
            pi.via_port = port;
            pi.role = (port == 2) ? AlarmRole::PORT2_PEER : AlarmRole::PORT3_PEER;
            peers.push_back(pi);
        }
    }
    return peers;
}

// ──────────────────── 内部辅助 ────────────────────

std::optional<int32_t> FiberTopologyResolver::find_intra_ne_peer(
        int32_t board_id, int32_t port) const {
    // 注意：调用者已持有 shared_lock
    PortKey pk{board_id, port};
    auto range = fiber_by_port_->equal_range(pk);
    for (auto it = range.first; it != range.second; ++it) {
        auto f_it = fiber_by_id_->find(it->second);
        if (f_it != fiber_by_id_->end() && !f_it->second.is_inter_ne) {
            const auto& entry = f_it->second;
            return (entry.src_board_id == board_id)
                ? entry.dst_board_id : entry.src_board_id;
        }
    }
    return std::nullopt;
}

void FiberTopologyResolver::resolve_scene(
        FiberTopologyInfo& info, const FiberCacheEntry& entry) const {
    // 注意：调用者已持有 shared_lock

    info.src_board_type = BoardType::ACTIVE; // 源端始终有源

    // 检查宿端是否为无源盘（Port-2 或 Port-3 有网元内连纤）
    bool is_passive_dst = false;
    for (int32_t port : {2, 3}) {
        PortKey pk{entry.dst_board_id, port};
        auto range = fiber_by_port_->equal_range(pk);
        for (auto it = range.first; it != range.second; ++it) {
            auto f_it = fiber_by_id_->find(it->second);
            if (f_it != fiber_by_id_->end() && !f_it->second.is_inter_ne) {
                is_passive_dst = true;
                break;
            }
        }
        if (is_passive_dst) break;
    }

    if (!is_passive_dst) {
        // ── 场景1：宿端有源盘 ──
        info.scene_type     = SceneType::SCENE_1;
        info.scenario_case  = ScenarioCase::CASE_0;
        info.dst_board_type = BoardType::ACTIVE;
        return;
    }

    // ── 场景2：宿端无源盘 ──
    info.scene_type     = SceneType::SCENE_2;
    info.dst_board_type = BoardType::PASSIVE;

    // 查找 Port-2 对端 (Board-B)
    auto peer_b = find_intra_ne_peer(entry.dst_board_id, 2);
    // 查找 Port-3 对端 (Board-A2)
    auto peer_a2 = find_intra_ne_peer(entry.dst_board_id, 3);

    bool has_port2 = peer_b.has_value();
    bool has_port3 = peer_a2.has_value();

    if (!has_port2) {
        // Case C：无 Port-2 连纤 → 固定 GREEN
        info.scenario_case = ScenarioCase::CASE_C;
        return;
    }

    // 填充主路对端 (Port-2 → Board-B)
    PeerInfo primary;
    primary.board_id = peer_b.value();
    primary.port_id  = 1;
    primary.via_port = 2;
    primary.role     = AlarmRole::PORT2_PEER;
    info.primary_peer = primary;

    if (has_port3) {
        // Case A：双路
        info.scenario_case = ScenarioCase::CASE_A;

        PeerInfo backup;
        backup.board_id = peer_a2.value();
        backup.port_id  = 1;
        backup.via_port = 3;
        backup.role     = AlarmRole::PORT3_PEER;
        info.backup_peer = backup;

        info.peers = {primary, backup};
    } else {
        // Case B：仅 Port-2
        info.scenario_case = ScenarioCase::CASE_B;
        info.peers = {primary};
    }
}

} // namespace fiber_maint
