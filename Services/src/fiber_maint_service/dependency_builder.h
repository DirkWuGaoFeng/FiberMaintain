#pragma once

/**
 * @file dependency_builder.h
 * @brief Layer 0 - 端口依赖索引构建器
 *
 * 核心数据结构：port_dependency_index_[PortKey] → SmallVector<DependencyEntry, 2>
 * 作用：将 find_affected_fibers() 从 O(n) 遍历优化为 O(1) 索引查找。
 *
 * 当告警事件到达时，通过 (board_id, port_id) 直接查到此端口
 * 关联的所有连纤及角色，立即触发颜色重算。
 */

#include "types.h"
#include <unordered_map>
#include <shared_mutex>

// 前向声明
struct FiberCacheEntry;

namespace fiber_maint {

class DependencyBuilder {
public:
    using FiberByIdMap   = std::unordered_map<int32_t, FiberCacheEntry>;
    using FiberByPortMap = std::unordered_multimap<PortKey, int32_t, PortKeyHash>;
    using IndexMap = std::unordered_map<
        PortKey, SmallVector<DependencyEntry, 2>, PortKeyHash>;

    DependencyBuilder() = default;

    /// 绑定缓存引用
    void bind(const FiberByIdMap* fiber_by_id,
              const FiberByPortMap* fiber_by_port,
              std::shared_mutex* cache_mutex);

    /// 构建单条连纤的依赖关系
    void build(int32_t fiber_id);

    /// 全量构建（分批 10000 条处理）
    void build_all();

    /// 移除连纤的依赖
    void remove(int32_t fiber_id);

    /// 网元内连纤变更时重建（先移除旧的，再重建）
    void rebuild(int32_t inter_ne_fiber_id);

    /// O(1) 查找：给定端口告警，返回受影响的连纤
    SmallVector<DependencyEntry, 2> lookup(PortKey port) const;

    /// 索引大小（用于监控）
    size_t index_size() const;

private:
    /// 为一条网元间连纤添加依赖条目
    void add_inter_ne_dependency(int32_t fiber_id,
                                 const FiberCacheEntry& entry);

    const FiberByIdMap*   fiber_by_id_   = nullptr;
    const FiberByPortMap* fiber_by_port_ = nullptr;
    std::shared_mutex*    cache_mutex_    = nullptr;

    /// 端口依赖索引（独立锁保护，不与缓存共享）
    mutable std::shared_mutex index_mutex_;
    IndexMap index_;
};

} // namespace fiber_maint
