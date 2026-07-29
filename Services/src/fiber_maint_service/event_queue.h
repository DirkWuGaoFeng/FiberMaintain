#pragma once

/**
 * @file event_queue.h
 * @brief Layer 0 - 合并事件队列（CoalescingEventQueue）
 *
 * 设计要点：
 * - alarm_pending_: HashMap 同 key 覆盖（同端口告警合并，减少 ~80%）
 * - fiber_queue_:   FIFO 有序（连纤事件不合并，保持顺序）
 * - drain(): 一次性取出所有待处理事件
 */

#include "types.h"
#include <unordered_map>
#include <deque>
#include <mutex>
#include <condition_variable>
#include <atomic>

namespace fiber_maint {

/// 告警事件的合并键（同 board_id + port_id 的告警覆盖旧值）
struct AlarmEventKey {
    int32_t board_id;
    int32_t port_id;

    bool operator==(const AlarmEventKey& o) const noexcept {
        return board_id == o.board_id && port_id == o.port_id;
    }
};

struct AlarmEventKeyHash {
    size_t operator()(const AlarmEventKey& k) const noexcept {
        return std::hash<int64_t>()(
            (static_cast<int64_t>(k.board_id) << 32) |
            static_cast<uint32_t>(k.port_id));
    }
};

/// 一次 drain 返回的事件批次
struct EventBatch {
    std::vector<QueueEvent> alarm_events;
    std::vector<QueueEvent> fiber_events;
    bool full_sync_done = false;
};

class CoalescingEventQueue {
public:
    CoalescingEventQueue() = default;

    /// 推入告警事件（同 key 覆盖：仅保留最新状态）
    void push_alarm(QueueEvent event) {
        std::lock_guard<std::mutex> lock(mutex_);
        AlarmEventKey key{event.board_id, event.port_id};
        alarm_pending_[key] = std::move(event);
        cv_.notify_one();
    }

    /// 推入连纤事件（FIFO 不合并）
    void push_fiber(QueueEvent event) {
        std::lock_guard<std::mutex> lock(mutex_);
        fiber_queue_.push_back(std::move(event));
        cv_.notify_one();
    }

    /// 标记全量同步完成
    void push_full_sync_done() {
        std::lock_guard<std::mutex> lock(mutex_);
        full_sync_done_ = true;
        cv_.notify_one();
    }

    /// 阻塞等待直到有事件可取，然后一次性 drain 所有事件
    EventBatch drain(std::atomic<bool>& running) {
        std::unique_lock<std::mutex> lock(mutex_);
        cv_.wait(lock, [&]() {
            return !alarm_pending_.empty() ||
                   !fiber_queue_.empty() ||
                   full_sync_done_ ||
                   !running;
        });

        EventBatch batch;

        // 告警：HashMap → vector（合并后的最新状态）
        batch.alarm_events.reserve(alarm_pending_.size());
        for (auto& [key, event] : alarm_pending_) {
            batch.alarm_events.push_back(std::move(event));
        }
        alarm_pending_.clear();

        // 连纤：FIFO 全量取出
        batch.fiber_events.reserve(fiber_queue_.size());
        for (auto& event : fiber_queue_) {
            batch.fiber_events.push_back(std::move(event));
        }
        fiber_queue_.clear();

        batch.full_sync_done = full_sync_done_;
        full_sync_done_ = false;

        return batch;
    }

    /// 非阻塞尝试 drain（用于优雅关闭时刷写）
    EventBatch try_drain() {
        std::lock_guard<std::mutex> lock(mutex_);
        EventBatch batch;

        batch.alarm_events.reserve(alarm_pending_.size());
        for (auto& [key, event] : alarm_pending_) {
            batch.alarm_events.push_back(std::move(event));
        }
        alarm_pending_.clear();

        batch.fiber_events.reserve(fiber_queue_.size());
        for (auto& event : fiber_queue_) {
            batch.fiber_events.push_back(std::move(event));
        }
        fiber_queue_.clear();

        batch.full_sync_done = full_sync_done_;
        full_sync_done_ = false;

        return batch;
    }

    /// 当前队列中的事件总数（用于监控）
    size_t pending_count() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return alarm_pending_.size() + fiber_queue_.size();
    }

private:
    mutable std::mutex mutex_;
    std::condition_variable cv_;

    /// 告警合并池：同 (board_id, port_id) 覆盖
    std::unordered_map<AlarmEventKey, QueueEvent, AlarmEventKeyHash>
        alarm_pending_;

    /// 连纤 FIFO 队列
    std::deque<QueueEvent> fiber_queue_;

    bool full_sync_done_ = false;
};

} // namespace fiber_maint
