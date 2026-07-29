/**
 * @file pull_callback.cpp
 * @brief Phase 2 - Pull Call 异步回调实现
 */

#include "fiber_maint_service_impl.h"
#include "pull_callback.h"
#include "alarm.grpc.pb.h"
#include "common/common.h"

namespace fiber_maint {

void PullCallbackThread::bind(
        std::shared_ptr<AlarmStub> stub,
        AlarmCache* alarm_cache,
        std::shared_mutex* cache_mutex,
        CoalescingEventQueue* event_queue,
        const std::string& callback_addr) {
    stub_ = std::move(stub);
    alarm_cache_ = alarm_cache;
    cache_mutex_ = cache_mutex;
    event_queue_ = event_queue;
    callback_addr_ = callback_addr;
}

void PullCallbackThread::start(std::atomic<bool>* running) {
    running_ = running;
    if (thread_.joinable()) thread_.join();
    thread_ = std::thread(&PullCallbackThread::run, this);
}

void PullCallbackThread::resync() {
    // 重新同步：停止旧线程，启动新线程
    if (running_ && *running_) {
        start(running_);
    }
}

void PullCallbackThread::run() {
    // 1. CreatePullCall
    Logger::instance().info("PullCallback: starting");
    fiber::alarm::CreatePullCallRequest req;
    req.set_include_history(false);
    req.set_callback_service_addr(callback_addr_);

    grpc::ClientContext ctx1;
    fiber::alarm::CreatePullCallResponse resp;
    auto status = stub_->CreatePullCall(&ctx1, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("PullCallback: CreatePullCall failed: {}",
            status.error_message());
        return;
    }

    std::string task_id = resp.task_id();
    Logger::instance().info("PullCallback: task_id={}", task_id);

    // 2. 轮询 GetPullCallResult（分批 10000/批）
    constexpr int BATCH_THRESHOLD = 10;
    int batch_count = 0;
    bool done = false;

    while (!done && running_ && *running_) {
        grpc::ClientContext ctx2;
        fiber::alarm::GetPullCallResultRequest get_req;
        get_req.set_task_id(task_id);
        fiber::alarm::GetPullCallResultResponse get_resp;

        auto gs = stub_->GetPullCallResult(&ctx2, get_req, &get_resp);
        if (!gs.ok()) {
            if (gs.error_code() == grpc::NOT_FOUND || 
                gs.error_code() == grpc::DEADLINE_EXCEEDED) {
                Logger::instance().error("PullCallback: task lost/expired, abort");
                break;  // 不再重试
            }
            // 指数退避
            std::this_thread::sleep_for(std::chrono::seconds(5));
            continue;
        }

        // 更新告警缓存
        {
            std::unique_lock<std::shared_mutex> lock(*cache_mutex_);
            for (const auto& alarm : get_resp.data()) {
                AlarmCacheKey key{
                    alarm.board_id(), alarm.port_id(),
                    static_cast<int8_t>(alarm.alarm_level())};
                (*alarm_cache_)[key] = {alarm.raised_at()};
            }
        }

        batch_count++;
        // 背压：每 10 批 sleep 10ms
        if (batch_count % BATCH_THRESHOLD == 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }

        if (get_resp.status() == "COMPLETED") {
            done = true;
        }
        else if (get_resp.status() == "FAILED") {
            Logger::instance().error("PullCallback: task failed");
            done = true;  // 失败也要退出
        }

        if (!done) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
    }

    if (done) {
        event_queue_->push_full_sync_done();
        Logger::instance().info("PullCallback: sync completed, {} batches",
            batch_count);
    }
}

} // namespace fiber_maint
