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
    static void request_completed(void* cls, struct MHD_Connection* connection,
                                  void** con_cls, MHD_RequestTerminationCode toe);
    MHD_Result process_request(struct MHD_Connection* connection,
                               const char* url, const char* method,
                               const std::string& post_body);
    
    // ── 公共 ──
    std::string handle_health();
    
    // ── BoardService (§2.1) ──
    std::string post_create_board(const std::string& body);
    std::string delete_board(int board_id);
    std::string get_board(int board_id);
    std::string post_batch_boards(const std::string& body);
    std::string list_boards();
    std::string get_board_fibers(int board_id);
    
    // ── TopologyService (§2.2) ──
    std::string post_create_fiber(const std::string& body);
    std::string delete_fiber(int fiber_id);
    std::string get_fiber(int fiber_id);
    std::string post_batch_fibers(const std::string& body);
    std::string get_fibers_by_port(int board_id, int port_id);
    std::string get_fiber_scene(int fiber_id);
    
    // ── PerformanceService (§2.3) ──
    std::string post_report_performance(const std::string& body);
    std::string get_current_performance(int board_id, int port_id);
    std::string get_history_performance(int board_id, int port_id,
                                        const std::string& start_time,
                                        const std::string& end_time);
    std::string post_batch_current_performance(const std::string& body);
    std::string post_batch_history_performance(const std::string& body);
    
    // ── AlarmService (§2.4) ──
    std::string post_report_alarm(const std::string& body);
    std::string post_clear_alarm(const std::string& body);
    std::string get_current_alarms(int board_id, int port_id);
    std::string post_batch_current_alarms(const std::string& body);
    
    // ── FiberMaintService (§2.5) ──
    std::string get_fiber_performance(int fiber_id);
    std::string post_batch_fiber_performance(const std::string& body);
    std::string get_fiber_history_performance(int fiber_id, const std::string& start_time, const std::string& end_time);
    std::string post_batch_fiber_history_performance(const std::string& body);
    std::string get_fiber_spanloss(int fiber_id);
    std::string post_batch_fiber_spanloss(const std::string& body);
    std::string get_colored_fibers(const std::string& color);
    std::string get_all_colored_fibers();
    std::string get_realtime_stats();
    std::string get_stats_trend(const std::string& start_time, const std::string& end_time);
    
    // ── 辅助 ──
    static MHD_Result send_response(struct MHD_Connection* connection,
                                    int status_code, const std::string& body);
    static int extract_id_from_path(const char* url, const char* prefix);
    static std::string extract_trailing_path(const char* url, const char* prefix);
    
    int port_;
    struct MHD_Daemon* daemon_;
    std::shared_ptr<fiber::board::BoardService::Stub> board_stub_;
    std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub_;
    std::shared_ptr<fiber::performance::PerformanceService::Stub> perf_stub_;
    std::shared_ptr<fiber::alarm::AlarmService::Stub> alarm_stub_;
    std::shared_ptr<fiber::maint::FiberMaintService::Stub> fiber_maint_stub_;
};
