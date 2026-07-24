#pragma once

#include <grpcpp/grpcpp.h>
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "performance.grpc.pb.h"
#include "alarm.grpc.pb.h"
#include "fiber_maint.grpc.pb.h"
#include "common/common.h"
#include <microhttpd.h>
#include <string>
#include <memory>

class HttpServer {
public:
    HttpServer();
    ~HttpServer();
    
    bool init(int port);
    void start();
    
private:
    static MHD_Result handle_request(void* cls, struct MHD_Connection* connection,
                                     const char* url, const char* method,
                                     const char* version, const char* upload_data,
                                     size_t* upload_data_size, void** con_cls);
    MHD_Result process_request(struct MHD_Connection* connection, const char* url, const char* method);
    
    std::string get_realtime_stats();
    std::string get_all_colored_fibers();
    std::string get_stats_trend(const std::string& start_time, const std::string& end_time);
    std::string get_fiber_scene(int fiber_id);
    
    int port_;
    struct MHD_Daemon* daemon_;
    std::shared_ptr<fiber::board::BoardService::Stub> board_stub_;
    std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub_;
    std::shared_ptr<fiber::performance::PerformanceService::Stub> perf_stub_;
    std::shared_ptr<fiber::alarm::AlarmService::Stub> alarm_stub_;
    std::shared_ptr<fiber::maint::FiberMaintService::Stub> fiber_maint_stub_;
};
