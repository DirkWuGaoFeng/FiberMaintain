#pragma once

#include <grpcpp/grpcpp.h>
#include "performance.grpc.pb.h"
#include "common/common.h"
#include <memory>
#include <thread>
#include <atomic>

class PerformanceServiceImpl : public fiber::performance::PerformanceService::Service {
public:
    PerformanceServiceImpl();
    ~PerformanceServiceImpl();
    
    bool init();
    
    grpc::Status ReportPerformance(grpc::ServerContext* context,
                                   const fiber::performance::ReportPerformanceRequest* request,
                                   fiber::performance::ReportPerformanceResponse* response) override;
    
    grpc::Status GetCurrentPerformance(grpc::ServerContext* context,
                                       const fiber::performance::GetCurrentPerformanceRequest* request,
                                       fiber::performance::GetCurrentPerformanceResponse* response) override;
    
    grpc::Status GetHistoryPerformance(grpc::ServerContext* context,
                                       const fiber::performance::GetHistoryPerformanceRequest* request,
                                       fiber::performance::GetHistoryPerformanceResponse* response) override;
    
    grpc::Status BatchGetCurrentPerformance(grpc::ServerContext* context,
                                            const fiber::performance::BatchGetCurrentPerformanceRequest* request,
                                            fiber::performance::BatchGetCurrentPerformanceResponse* response) override;
    
    grpc::Status BatchGetHistoryPerformance(grpc::ServerContext* context,
                                            const fiber::performance::BatchGetHistoryPerformanceRequest* request,
                                            fiber::performance::BatchGetHistoryPerformanceResponse* response) override;
    
    grpc::Status HealthCheck(grpc::ServerContext* context,
                             const fiber::performance::HealthCheckRequest* request,
                             fiber::common::HealthCheckResponse* response) override;
    
private:
    void archive_task();
    std::thread archive_thread_;
    std::atomic<bool> running_;
};