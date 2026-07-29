#pragma once

/**
 * @file flap_detector.h
 * @brief Phase 2 - 闪断抑制检测器
 *
 * 三级闪断抑制：
 *   L1: CoalescingEventQueue 告警合并（~80%）
 *   L2: OutputLayer 同 fiber 去重（~75%）
 *   L3: FlapDetector 时间窗口检测
 *
 * 规则：1 秒窗口内翻转 > 10 次 → 抑制 2 秒
 */

#include <unordered_map>
#include <deque>
#include <chrono>
#include <mutex>
#include <cstdint>

namespace fiber_maint {

class FlapDetector {
public:
    explicit FlapDetector(
            int window_ms = 1000,
            int threshold = 10,
            int suppress_ms = 2000)
        : window_ms_(window_ms)
        , threshold_(threshold)
        , suppress_ms_(suppress_ms) {}

    /// 记录一次状态变化，返回 true = 正常处理，false = 被抑制
    bool record_change(int32_t fiber_id) {
        std::lock_guard<std::mutex> lock(mutex_);

        auto now = std::chrono::steady_clock::now();
        auto& entry = history_[fiber_id];

        // 检查是否处于抑制期
        if (entry.suppressed_until.time_since_epoch().count() > 0 &&
            now < entry.suppressed_until) {
            return false; // 被抑制
        }

        // 记录变化时间戳
        entry.timestamps.push_back(now);

        // 清理窗口外的记录
        auto cutoff = now - std::chrono::milliseconds(window_ms_);
        while (!entry.timestamps.empty() &&
               entry.timestamps.front() < cutoff) {
            entry.timestamps.pop_front();
        }

        // 检查是否超过阈值
        if (static_cast<int>(entry.timestamps.size()) > threshold_) {
            entry.suppressed_until = now +
                std::chrono::milliseconds(suppress_ms_);
            entry.timestamps.clear();
            return false; // 开始抑制
        }

        return true;
    }

    /// 检查某个 fiber 是否当前被抑制
    bool is_suppressed(int32_t fiber_id) const {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = history_.find(fiber_id);
        if (it == history_.end()) return false;
        auto now = std::chrono::steady_clock::now();
        return it->second.suppressed_until > now;
    }

    /// 清理过期记录（定期调用）
    void cleanup() {
        std::lock_guard<std::mutex> lock(mutex_);
        auto now = std::chrono::steady_clock::now();
        auto cutoff = now - std::chrono::milliseconds(window_ms_ * 2);

        for (auto it = history_.begin(); it != history_.end(); ) {
            if (it->second.timestamps.empty() &&
                it->second.suppressed_until < now) {
                it = history_.erase(it);
            } else {
                // 清理旧时间戳
                while (!it->second.timestamps.empty() &&
                       it->second.timestamps.front() < cutoff) {
                    it->second.timestamps.pop_front();
                }
                ++it;
            }
        }
    }

private:
    struct FlapEntry {
        std::deque<std::chrono::steady_clock::time_point> timestamps;
        std::chrono::steady_clock::time_point suppressed_until{};
    };

    mutable std::mutex mutex_;
    std::unordered_map<int32_t, FlapEntry> history_;

    int window_ms_;
    int threshold_;
    int suppress_ms_;
};

} // namespace fiber_maint
