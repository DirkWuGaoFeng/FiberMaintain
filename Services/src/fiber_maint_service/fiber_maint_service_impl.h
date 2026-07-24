#pragma once

#include <grpcpp/grpcpp.h>
#include "fiber_maint.grpc.pb.h"
#include "alarm.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "performance.grpc.pb.h"
#include "common/common.h"
#include <memory>
#include <mutex>
#include <unordered_map>
#include <unordered_set>
#include <queue>
#include <thread>
#include <atomic>
#include <future>
#include <algorithm>

struct FiberCacheEntry {
    int32_t fiber_id;
    int32_t src_board_id;
    int8_t  src_port_id;
    int32_t src_ne_id;
    int32_t dst_board_id;
    int8_t  dst_port_id;
    int32_t dst_ne_id;
    bool    is_inter_ne;
};

struct AlarmCacheKey {
    int32_t board_id;
    int8_t  port_id;
    int8_t  alarm_level;
    
    bool operator==(const AlarmCacheKey& o) const {
        return board_id == o.board_id && port_id == o.port_id && alarm_level == o.alarm_level;
    }
};

struct AlarmCacheKeyHash {
    size_t operator()(const AlarmCacheKey& k) const {
        return std::hash<int64_t>()(
            (static_cast<int64_t>(k.board_id) << 16) |
            (static_cast<int64_t>(k.port_id) << 8) |
            k.alarm_level
        );
    }
};

struct PortKeyHash {
    size_t operator()(const std::pair<int32_t, int8_t>& k) const {
        return std::hash<int64_t>()(
            (static_cast<int64_t>(k.first) << 8) |
            static_cast<uint8_t>(k.second)
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

struct ColorRecalcTask {
    int32_t fiber_id;
    std::function<void()> task;
};

struct FiberColorCacheEntry {
    int8_t color;
    int32_t scene_type;
};

class FiberMaintServiceImpl : public fiber::maint::FiberMaintService::Service {
public:
    FiberMaintServiceImpl();
    ~FiberMaintServiceImpl();
    
    bool init();
    
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
    void subscribe_alarm_events();
    void subscribe_fiber_events();
    void process_alarm_event(const fiber::alarm::AlarmEvent& event);
    void process_fiber_event(const fiber::topology::FiberEvent& event);
    void sync_alarm_cache();
    void sync_fiber_cache();
    void sync_color_cache();
    void full_color_recalc();
    void trend_task();
    void color_recalc_worker();
    void enqueue_color_recalc(int32_t fiber_id, std::function<void()> task);
    void init_alarm_sync_async();
    void push_color_event(const fiber::maint::FiberColorEvent& event);
    
    std::string get_callback_addr();
    
    bool has_alarm(int32_t board_id, int8_t port_id, int8_t alarm_level);
    PortAlarmSummary get_port_alarm_summary(int32_t board_id, int8_t port_id);
    int8_t calculate_color(int32_t fiber_id, int32_t& scene_type, int32_t& scenario_case);
    void update_fiber_color(int32_t fiber_id, int8_t new_color, int32_t scene_type, int32_t scenario_case);
    void recalculate_fiber_color(int32_t fiber_id);
    void init_fiber_color(const FiberCacheEntry& entry);
    
    std::vector<int32_t> find_affected_fibers(int32_t board_id, int8_t port_id);
    
    std::mutex fiber_cache_mutex_;
    std::unordered_map<int32_t, FiberCacheEntry> fiber_by_id_;
    std::unordered_multimap<std::pair<int32_t,int8_t>, int32_t, PortKeyHash> fiber_by_port_;
    
    std::mutex color_cache_mutex_;
    std::unordered_map<int32_t, FiberColorCacheEntry> color_by_fiber_;
    
    std::mutex alarm_cache_mutex_;
    std::unordered_map<AlarmCacheKey, AlarmCacheValue, AlarmCacheKeyHash> alarm_cache_;
    
    std::mutex task_mutex_;
    std::condition_variable task_cv_;
    std::unordered_map<int32_t, std::queue<std::function<void()>>> recalc_tasks_;
    std::unordered_set<int32_t> running_fibers_;
    
    std::mutex writer_mutex_;
    std::vector<grpc::ServerWriter<fiber::maint::FiberColorEvent>*> color_event_writers_;
    
    std::atomic<bool> running_;
    
    std::thread alarm_sub_thread_;
    std::thread fiber_sub_thread_;
    std::thread trend_thread_;
    std::vector<std::thread> worker_threads_;
    
    std::shared_ptr<fiber::alarm::AlarmService::Stub> alarm_stub_;
    std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub_;
    std::shared_ptr<fiber::performance::PerformanceService::Stub> perf_stub_;
};