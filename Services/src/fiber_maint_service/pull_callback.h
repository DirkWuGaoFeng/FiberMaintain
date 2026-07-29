#pragma once

/**
 * @file pull_callback.h
 * @brief Phase 2 - Pull Call 异步回调线程
 *
 * PullCallbackThread：异步 CreatePullCall + 轮询 GetPullCallResult。
 * 分批接收告警（10000/批, 每10批 sleep(10ms) 背压）。
 * 完成后 push_full_sync_done() 到事件队列。
 */

#include "types.h"
#include "event_queue.h"
#include <memory>
#include <thread>
#include <atomic>
#include <shared_mutex>
#include <unordered_map>

namespace fiber { namespace alarm { class AlarmService; } }

struct AlarmCacheKey;
struct AlarmCacheValue;

namespace fiber_maint {

class PullCallbackThread {
public:
    using AlarmStub = fiber::alarm::AlarmService::Stub;
    using AlarmCache = std::unordered_map<AlarmCacheKey, AlarmCacheValue,
                                          AlarmCacheKeyHash>;

    PullCallbackThread() = default;

    void bind(std::shared_ptr<AlarmStub> stub,
              AlarmCache* alarm_cache,
              std::shared_mutex* cache_mutex,
              CoalescingEventQueue* event_queue,
              const std::string& callback_addr);

    /// 启动异步同步
    void start(std::atomic<bool>* running);

    /// 断线后重新同步
    void resync();

private:
    void run();

    std::shared_ptr<AlarmStub>  stub_;
    AlarmCache*                 alarm_cache_ = nullptr;
    std::shared_mutex*          cache_mutex_ = nullptr;
    CoalescingEventQueue*       event_queue_ = nullptr;
    std::string                 callback_addr_;
    std::atomic<bool>*          running_ = nullptr;
    std::thread                 thread_;
};

} // namespace fiber_maint
