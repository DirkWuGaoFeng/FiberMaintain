#pragma once

#include <grpcpp/grpcpp.h>
#include "alarm.grpc.pb.h"
#include "common/common.h"
#include <memory>
#include <mutex>
#include <condition_variable>
#include <queue>
#include <unordered_map>
#include <thread>
#include <atomic>
#include <chrono>

struct PullCallTask {
    std::string task_id;
    std::vector<fiber::alarm::PortRef> ports;
    bool include_history;
    std::vector<fiber::alarm::AlarmRecord> data;
    std::string status;
    std::chrono::steady_clock::time_point expire_time;
    std::string callback_service_addr;
};

class AlarmServiceImpl : public fiber::alarm::AlarmService::Service {
public:
    AlarmServiceImpl();
    ~AlarmServiceImpl();
    
    bool init();
    
    grpc::Status ReportAlarm(grpc::ServerContext* context,
                             const fiber::alarm::ReportAlarmRequest* request,
                             fiber::alarm::ReportAlarmResponse* response) override;
    
    grpc::Status ClearAlarm(grpc::ServerContext* context,
                            const fiber::alarm::ClearAlarmRequest* request,
                            fiber::alarm::ClearAlarmResponse* response) override;
    
    grpc::Status GetCurrentAlarm(grpc::ServerContext* context,
                                 const fiber::alarm::GetCurrentAlarmRequest* request,
                                 fiber::alarm::GetCurrentAlarmResponse* response) override;
    
    grpc::Status BatchGetCurrentAlarms(grpc::ServerContext* context,
                                       const fiber::alarm::BatchGetCurrentAlarmsRequest* request,
                                       fiber::alarm::BatchGetCurrentAlarmsResponse* response) override;
    
    grpc::Status SubscribeAlarmEvents(grpc::ServerContext* context,
                                      const fiber::alarm::SubscribeAlarmEventsRequest* request,
                                      grpc::ServerWriter<fiber::alarm::AlarmEvent>* writer) override;
    
    grpc::Status CreatePullCall(grpc::ServerContext* context,
                                const fiber::alarm::CreatePullCallRequest* request,
                                fiber::alarm::CreatePullCallResponse* response) override;
    
    grpc::Status GetPullCallResult(grpc::ServerContext* context,
                                   const fiber::alarm::GetPullCallResultRequest* request,
                                   fiber::alarm::GetPullCallResultResponse* response) override;
    
    grpc::Status CancelPullCall(grpc::ServerContext* context,
                                const fiber::alarm::CancelPullCallRequest* request,
                                fiber::alarm::CancelPullCallResponse* response) override;
    
    grpc::Status HealthCheck(grpc::ServerContext* context,
                              const fiber::alarm::HealthCheckRequest* request,
                              fiber::common::HealthCheckResponse* response) override;
    
    void push_alarm_event(const fiber::alarm::AlarmEvent& event);
    
private:
    void cleanup_task();
    void process_pull_call_task(const std::string& task_id);
    
    std::mutex event_mutex_;
    std::condition_variable event_cv_;
    std::vector<fiber::alarm::AlarmEvent> event_buffer_;
    std::atomic<bool> running_;
    
    std::mutex task_mutex_;
    std::unordered_map<std::string, PullCallTask> pull_call_tasks_;
    
    std::thread cleanup_thread_;
    
    std::string generate_task_id();
};