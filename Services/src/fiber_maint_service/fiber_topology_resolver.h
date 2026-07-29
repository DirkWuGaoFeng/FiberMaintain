#pragma once

/**
 * @file fiber_topology_resolver.h
 * @brief Layer 1 - 光纤拓扑解析器
 *
 * 职责：根据 fiber_id 解析完整拓扑信息（场景类型、单盘类型、对端信息）。
 * 所有 Layer 2/3 组件通过此解析器获取拓扑上下文，避免重复遍历缓存。
 */

#include "types.h"
#include <unordered_map>
#include <shared_mutex>
#include <optional>

// 前向声明 — 避免引入 impl 头文件
struct FiberCacheEntry;

namespace fiber_maint {

class FiberTopologyResolver {
public:
    /// 缓存引用（由 FiberMaintServiceImpl 在构造时传入）
    using FiberByIdMap  = std::unordered_map<int32_t, FiberCacheEntry>;
    using FiberByPortMap = std::unordered_multimap<PortKey, int32_t, PortKeyHash>;

    FiberTopologyResolver() = default;

    /// 绑定缓存引用（不拥有所有权，仅持有指针）
    void bind(const FiberByIdMap* fiber_by_id,
              const FiberByPortMap* fiber_by_port,
              std::shared_mutex* cache_mutex);

    /**
     * @brief 解析单条连纤的完整拓扑
     * @return 拓扑信息；fiber_id 不存在时 is_inter_ne = false
     */
    FiberTopologyInfo resolve(int32_t fiber_id) const;

    /// 批量解析
    std::vector<FiberTopologyInfo> resolve_batch(
        const std::vector<int32_t>& fiber_ids) const;

    /// 通过端口查找关联的网元间连纤
    std::vector<int32_t> get_inter_ne_fibers_by_port(PortKey port) const;

    /// 通过端口查找关联的网元内连纤
    std::optional<int32_t> get_intra_ne_fiber_by_port(PortKey port) const;

    /// 判定单盘类型
    BoardType classify_board(int32_t board_id) const;

    /// 在无源盘上查找所有对端（排除指定端口）
    std::vector<PeerInfo> find_peers_on_passive_board(
        int32_t board_id, int32_t exclude_port = 0) const;

private:
    /// 在 port 上查找网元内连纤的对端单盘
    std::optional<int32_t> find_intra_ne_peer(
        int32_t board_id, int32_t port) const;

    /// 场景判定核心逻辑
    void resolve_scene(FiberTopologyInfo& info,
                       const FiberCacheEntry& entry) const;

    const FiberByIdMap*   fiber_by_id_  = nullptr;
    const FiberByPortMap* fiber_by_port_ = nullptr;
    std::shared_mutex*    cache_mutex_   = nullptr;
};

} // namespace fiber_maint
