/**
 * @file dependency_builder.cpp
 * @brief Layer 0 - 端口依赖索引实现
 */

#include "dependency_builder.h"
#include "fiber_maint_service_impl.h"
#include "common/common.h"

namespace fiber_maint {

void DependencyBuilder::bind(
        const FiberByIdMap* fiber_by_id,
        const FiberByPortMap* fiber_by_port,
        std::shared_mutex* cache_mutex) {
    fiber_by_id_   = fiber_by_id;
    fiber_by_port_ = fiber_by_port;
    cache_mutex_   = cache_mutex;
}

// ──────────────────── add_inter_ne_dependency ────────────────────

void DependencyBuilder::add_inter_ne_dependency(
        int32_t fiber_id, const FiberCacheEntry& entry) {
    // 检查宿端是否为无源盘
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
        // 场景1：宿端有源盘 Port-1
        PortKey key{entry.dst_board_id, 1};
        index_[key].push_back({fiber_id, AlarmRole::DST_ACTIVE});
        return;
    }

    // 场景2：宿端无源盘
    // Port-2 对端 (Board-B)
    {
        PortKey pk{entry.dst_board_id, 2};
        auto range = fiber_by_port_->equal_range(pk);
        for (auto it = range.first; it != range.second; ++it) {
            auto f_it = fiber_by_id_->find(it->second);
            if (f_it != fiber_by_id_->end() && !f_it->second.is_inter_ne) {
                const auto& intra = f_it->second;
                int32_t board_B = (intra.src_board_id == entry.dst_board_id)
                    ? intra.dst_board_id : intra.src_board_id;
                PortKey key{board_B, 1};
                index_[key].push_back({fiber_id, AlarmRole::PORT2_PEER});
                break;
            }
        }
    }

    // Port-3 对端 (Board-A2)
    {
        PortKey pk{entry.dst_board_id, 3};
        auto range = fiber_by_port_->equal_range(pk);
        for (auto it = range.first; it != range.second; ++it) {
            auto f_it = fiber_by_id_->find(it->second);
            if (f_it != fiber_by_id_->end() && !f_it->second.is_inter_ne) {
                const auto& intra = f_it->second;
                int32_t board_A2 = (intra.src_board_id == entry.dst_board_id)
                    ? intra.dst_board_id : intra.src_board_id;
                PortKey key{board_A2, 1};
                index_[key].push_back({fiber_id, AlarmRole::PORT3_PEER});
                break;
            }
        }
    }
}

// ──────────────────── build / build_all ────────────────────

void DependencyBuilder::build(int32_t fiber_id) {
    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) return;

    std::shared_lock<std::shared_mutex> cache_lock(*cache_mutex_);

    auto it = fiber_by_id_->find(fiber_id);
    if (it == fiber_by_id_->end()) return;
    if (!it->second.is_inter_ne) return;

    std::unique_lock<std::shared_mutex> idx_lock(index_mutex_);
    add_inter_ne_dependency(fiber_id, it->second);
}

void DependencyBuilder::build_all() {
    if (!fiber_by_id_ || !fiber_by_port_ || !cache_mutex_) return;

    std::shared_lock<std::shared_mutex> cache_lock(*cache_mutex_);
    std::unique_lock<std::shared_mutex> idx_lock(index_mutex_);

    index_.clear();
    index_.reserve(2000000); // 百万级预分配

    constexpr int BATCH_SIZE = 10000;
    int count = 0;

    for (const auto& [fid, entry] : *fiber_by_id_) {
        if (!entry.is_inter_ne) continue;

        add_inter_ne_dependency(fid, entry);
        ++count;

        // 每 BATCH_SIZE 条释放索引锁让读取不被长期阻塞
        if (count >= BATCH_SIZE) {
            idx_lock.unlock();
            idx_lock.lock();
            count = 0;
        }
    }

    Logger::instance().info("DependencyBuilder: built {} entries", index_.size());
}

// ──────────────────── remove / rebuild ────────────────────

void DependencyBuilder::remove(int32_t fiber_id) {
    std::unique_lock<std::shared_mutex> lock(index_mutex_);

    for (auto it = index_.begin(); it != index_.end(); ) {
        auto& vec = it->second;
        bool found = false;
        // SmallVector 很小（通常 ≤2 个元素），线性扫描即可
        for (size_t i = 0; i < vec.size(); ++i) {
            if (vec[i].fiber_id == fiber_id) {
                found = true;
                break;
            }
        }
        if (found && vec.size() <= 1) {
            it = index_.erase(it);
        } else if (found) {
            // 移除匹配的元素（保留其他）
            SmallVector<DependencyEntry, 2> new_vec;
            for (size_t i = 0; i < vec.size(); ++i) {
                if (vec[i].fiber_id != fiber_id) {
                    new_vec.push_back(vec[i]);
                }
            }
            it->second = new_vec;
            ++it;
        } else {
            ++it;
        }
    }
}

void DependencyBuilder::rebuild(int32_t inter_ne_fiber_id) {
    remove(inter_ne_fiber_id);
    build(inter_ne_fiber_id);
}

// ──────────────────── lookup ────────────────────

SmallVector<DependencyEntry, 2> DependencyBuilder::lookup(PortKey port) const {
    std::shared_lock<std::shared_mutex> lock(index_mutex_);
    auto it = index_.find(port);
    if (it != index_.end()) {
        return it->second;
    }
    return {};
}

size_t DependencyBuilder::index_size() const {
    std::shared_lock<std::shared_mutex> lock(index_mutex_);
    return index_.size();
}

} // namespace fiber_maint
