#pragma once

/**
 * @file output_layer.h
 * @brief Phase 2 - 异步输出层
 *
 * OutputThread 从 SPSC 队列消费 ChangeRecord：
 * - 批量 DB 写入（256/批, 3次重试, WAL 兜底）
 * - 同 fiber 去重（GREEN→RED→YELLOW 合并为 GREEN→YELLOW）
 * - WebSocket/gRPC 颜色事件推送
 */

#include "types.h"
#include "spsc_queue.h"
#include <thread>
#include <atomic>
#include <functional>
#include <mutex>
#include <vector>
#include <unordered_map>
#include <shared_mutex>

namespace fiber_maint {

/// 输出层回调类型（用于 WebSocket/gRPC 推送）
using ColorPushCallback = std::function<void(const ChangeRecord&)>;

class OutputThread {
public:
    OutputThread();
    ~OutputThread();

    /// 设置 SPSC 队列引用
    void bind(SPSCQueue<ChangeRecord>* queue,
              std::shared_mutex* color_mutex,
              std::unordered_map<int32_t, ColorContext>* color_contexts);

    /// 设置颜色推送回调
    void set_push_callback(ColorPushCallback cb);

    /// 启动输出线程
    void start(std::atomic<bool>* running);

    /// 优雅关闭（等待队列刷写，最多 10s）
    void shutdown();

    /// 外部推入变更（由 event_process_loop 调用）
    void enqueue(ChangeRecord record);

private:
    void run();

    /// 批量写入 DB（256 条/批，3 次重试）
    bool batch_write_db(std::vector<ChangeRecord>& records);

    /// 写 WAL 兜底
    void write_wal(const std::vector<ChangeRecord>& records);

    SPSCQueue<ChangeRecord>* queue_ = nullptr;
    std::shared_mutex* color_mutex_ = nullptr;
    std::unordered_map<int32_t, ColorContext>* color_contexts_ = nullptr;

    ColorPushCallback push_cb_;
    std::thread thread_;
    std::atomic<bool>* running_ = nullptr;

    /// 同 fiber 去重缓存
    std::unordered_map<int32_t, ChangeRecord> dedup_buffer_;
};

} // namespace fiber_maint
