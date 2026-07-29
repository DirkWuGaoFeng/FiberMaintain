#pragma once

/**
 * @file fiber_maint_service_impl.h
 * @brief FiberMaintService v4.0 — 重构后的核心服务实现
 *
 * 四层架构集成：
 *   Layer 0: types.h (数据结构) + event_queue.h (事件引擎) + dependency_builder (索引)
 *   Layer 1: fiber_topology_resolver (拓扑解析)
 *   Layer 2: target_builders (查询目标构建)
 *   Layer 3: color_strategy + perf_executor + spanloss_calculator
 */

#include <grpcpp/grpcpp.h>
#include "fiber_maint.grpc.pb.h"
#include "alarm.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "performance.grpc.pb.h"
#include "common/common.h"

// v4.0 数据结构（前置定义，供组件头文件使用）
#include "types.h"

struct FiberCacheEntry {
    int32_t fiber_id;
    int32_t src_board_id;
    int32_t src_port_id;       // v4.0: int8_t → int32_t
    int32_t src_ne_id;
    int32_t dst_board_id;
    int32_t dst_port_id;       // v4.0: int8_t → int32_t
    int32_t dst_ne_id;
    bool    is_inter_ne;
};

struct AlarmCacheKey {
    int32_t board_id;
    int32_t port_id;           // v4.0: int8_t → int32_t
    int8_t  alarm_level;

    bool operator==(const AlarmCacheKey& o) const {
        return board_id == o.board_id && port_id == o.port_id
            && alarm_level == o.alarm_level;
    }
};

struct AlarmCacheKeyHash {
    size_t operator()(const AlarmCacheKey& k) const {
        return std::hash<int64_t>()(
            (static_cast<int64_t>(k.board_id) << 24) |
            (static_cast<int64_t>(k.port_id) << 8) |
            k.alarm_level
        );
    }
};

struct AlarmCacheValue {
    std::string raised_at;
};

struct PortAlarmSummary {
    bool has_critical;
    bool has_minor;
};

struct FiberColorCacheEntry {
    int8_t  color;
    int32_t scene_type;
};

// v4.0 四层架构组件
#include "fiber_topology_resolver.h"
#include "color_strategy.h"
#include "perf_executor.h"
#include "spanloss_calculator.h"
#include "dependency_builder.h"
#include "event_queue.h"
#include "spsc_queue.h"
#include "output_layer.h"
#include "pull_callback.h"
#include "flap_detector.h"

#include <memory>
#include <shared_mutex>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <thread>
#include <atomic>
#include <functional>
#include <condition_variable>

// ============================================================
//  FiberMaintServiceImpl
// ============================================================

class FiberMaintServiceImpl : public fiber::maint::FiberMaintService::Service {
public:
    FiberMaintServiceImpl();
    ~FiberMaintServiceImpl();

    bool init();

    // ──────── gRPC Handler（接口签名不变） ────────

    grpc::Status GetFiberPerformance(grpc::ServerContext* context,
        const fiber::maint::GetFiberPerformanceRequest* request,
        fiber::maint::GetFiberPerformanceResponse* response) override;

    grpc::Status BatchGetFiberPerformance(grpc::ServerContext* context,
        const fiber::maint::BatchGetFiberPerformanceRequest* request,
        fiber::maint::BatchGetFiberPerformanceResponse* response) override;

    grpc::Status GetFiberHistoryPerformance(grpc::ServerContext* context,
        const fiber::maint::GetFiberHistoryPerformanceRequest* request,
        fiber::maint::GetFiberHistoryPerformanceResponse* response) override;

    grpc::Status BatchGetFiberHistoryPerformance(grpc::ServerContext* context,
        const fiber::maint::BatchGetFiberHistoryPerformanceRequest* request,
        fiber::maint::BatchGetFiberHistoryPerformanceResponse* response) override;

    grpc::Status GetFiberSpanloss(grpc::ServerContext* context,
        const fiber::maint::GetFiberSpanlossRequest* request,
        fiber::maint::GetFiberSpanlossResponse* response) override;

    grpc::Status BatchGetFiberSpanloss(grpc::ServerContext* context,
        const fiber::maint::BatchGetFiberSpanlossRequest* request,
        fiber::maint::BatchGetFiberSpanlossResponse* response) override;

    grpc::Status GetColoredFibers(grpc::ServerContext* context,
        const fiber::maint::GetColoredFibersRequest* request,
        fiber::maint::GetColoredFibersResponse* response) override;

    grpc::Status GetAllColoredFibers(grpc::ServerContext* context,
        const fiber::maint::GetAllColoredFibersRequest* request,
        fiber::maint::GetAllColoredFibersResponse* response) override;

    grpc::Status GetFiberStatsRealtime(grpc::ServerContext* context,
        const fiber::maint::GetFiberStatsRealtimeRequest* request,
        fiber::maint::GetFiberStatsRealtimeResponse* response) override;

    grpc::Status GetFiberStatsTrend(grpc::ServerContext* context,
        const fiber::maint::GetFiberStatsTrendRequest* request,
        fiber::maint::GetFiberStatsTrendResponse* response) override;

    grpc::Status SubscribeFiberColorEvents(grpc::ServerContext* context,
        const fiber::maint::SubscribeFiberColorEventsRequest* request,
        grpc::ServerWriter<fiber::maint::FiberColorEvent>* writer) override;

    grpc::Status PullCallResultCallback(grpc::ServerContext* context,
        const fiber::maint::PullCallResultCallbackRequest* request,
        fiber::maint::PullCallResultCallbackResponse* response) override;

    grpc::Status HealthCheck(grpc::ServerContext* context,
        const fiber::maint::HealthCheckRequest* request,
        fiber::common::HealthCheckResponse* response) override;

private:
    // ──────── 事件订阅 & 处理 ────────
    void subscribe_alarm_events();
    void subscribe_fiber_events();
    void process_alarm_event(const fiber::alarm::AlarmEvent& event);
    void process_fiber_event(const fiber::topology::FiberEvent& event);

    // ──────── v4.0 事件驱动主循环 ────────
    void event_process_loop();

    // ──────── 同步 & 缓存 ────────
    void sync_alarm_cache();
    void sync_fiber_cache();
    void sync_color_cache();
    void full_color_recalc();
    void init_alarm_sync_async();

    // ──────── 颜色计算（委托 IColorStrategy） ────────
    int8_t calculate_color(int32_t fiber_id, int32_t& scene_type,
                           int32_t& scenario_case);
    void update_fiber_color(int32_t fiber_id, int8_t new_color,
                            int32_t scene_type, int32_t scenario_case);
    void recalculate_fiber_color(int32_t fiber_id);
    void init_fiber_color(const FiberCacheEntry& entry);

    // ──────── 辅助 ────────
    bool has_alarm(int32_t board_id, int32_t port_id, int8_t alarm_level);
    PortAlarmSummary get_port_alarm_summary(int32_t board_id, int32_t port_id);
    void push_color_event(const fiber::maint::FiberColorEvent& event);
    std::string get_callback_addr();
    void trend_task();

    // ──────── 数据缓存（shared_mutex 读写隔离） ────────
    std::shared_mutex cache_rw_mutex_;

    std::unordered_map<int32_t, FiberCacheEntry> fiber_by_id_;
    std::unordered_multimap<fiber_maint::PortKey, int32_t,
                            fiber_maint::PortKeyHash> fiber_by_port_;
    std::unordered_map<AlarmCacheKey, AlarmCacheValue,
                       AlarmCacheKeyHash> alarm_cache_;
    std::unordered_map<int32_t, FiberColorCacheEntry> color_by_fiber_;
    std::unordered_map<int32_t, fiber_maint::ColorContext> color_contexts_;

    // ──────── v4.0 四层架构组件 ────────
    fiber_maint::FiberTopologyResolver  resolver_;
    fiber_maint::ScenarioRegistry       registry_;
    fiber_maint::DependencyBuilder      dep_builder_;
    fiber_maint::CoalescingEventQueue   event_queue_;

    std::unique_ptr<fiber_maint::PerfQueryExecutor>   perf_executor_;
    std::unique_ptr<fiber_maint::SpanlossCalculator>   spanloss_calc_;

    // ──────── 线程 ────────
    std::atomic<bool> running_;
    std::atomic<fiber_maint::SyncState> sync_state_{
        fiber_maint::SyncState::STARTING};

    std::thread alarm_sub_thread_;
    std::thread fiber_sub_thread_;
    std::thread trend_thread_;
    std::thread event_process_thread_;

    // ──────── gRPC 事件推送 ────────
    std::mutex writer_mutex_;
    std::vector<grpc::ServerWriter<fiber::maint::FiberColorEvent>*>
        color_event_writers_;

    // ──────── gRPC Stubs ────────
    std::shared_ptr<fiber::alarm::AlarmService::Stub>       alarm_stub_;
    std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub_;
    std::shared_ptr<fiber::performance::PerformanceService::Stub> perf_stub_;

    // ──────── Phase 2 组件 ────────
    fiber_maint::SPSCQueue<fiber_maint::ChangeRecord> output_queue_;
    fiber_maint::OutputThread      output_thread_;
    fiber_maint::PullCallbackThread pull_callback_;
    fiber_maint::FlapDetector      flap_detector_;
};