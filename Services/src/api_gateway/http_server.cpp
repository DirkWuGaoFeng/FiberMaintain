#include "http_server.h"
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "performance.grpc.pb.h"
#include "alarm.grpc.pb.h"
#include "fiber_maint.grpc.pb.h"
#include "common/common.h"
#include <microhttpd.h>
#include <string>
#include <memory>
#include <iostream>

HttpServer::HttpServer() : port_(8080), daemon_(nullptr) {}

HttpServer::~HttpServer() {
    if (daemon_) {
        MHD_stop_daemon(daemon_);
    }
}

bool HttpServer::init(int port) {
    port_ = port;
    
    std::string board_addr = Config::instance().get_string("board_service.addr", "localhost:50051");
    std::string topology_addr = Config::instance().get_string("topology_service.addr", "localhost:50052");
    std::string perf_addr = Config::instance().get_string("performance_service.addr", "localhost:50053");
    std::string alarm_addr = Config::instance().get_string("alarm_service.addr", "localhost:50054");
    std::string fiber_maint_addr = Config::instance().get_string("fiber_maint_service.addr", "localhost:50055");
    
    board_stub_ = fiber::board::BoardService::NewStub(grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials()));
    topology_stub_ = fiber::topology::TopologyService::NewStub(grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials()));
    perf_stub_ = fiber::performance::PerformanceService::NewStub(grpc::CreateChannel(perf_addr, grpc::InsecureChannelCredentials()));
    alarm_stub_ = fiber::alarm::AlarmService::NewStub(grpc::CreateChannel(alarm_addr, grpc::InsecureChannelCredentials()));
    fiber_maint_stub_ = fiber::maint::FiberMaintService::NewStub(grpc::CreateChannel(fiber_maint_addr, grpc::InsecureChannelCredentials()));
    
    return true;
}

MHD_Result HttpServer::handle_request(void* cls, struct MHD_Connection* connection,
                                     const char* url, const char* method,
                                     const char* version, const char* upload_data,
                                     size_t* upload_data_size, void** con_cls) {
    HttpServer* server = static_cast<HttpServer*>(cls);
    return server->process_request(connection, url, method);
}

MHD_Result HttpServer::process_request(struct MHD_Connection* connection, const char* url, const char* method) {
    std::string response_body;
    int status_code = MHD_HTTP_NOT_FOUND;
    
    if (strcmp(method, "GET") == 0) {
        if (strcmp(url, "/health") == 0) {
            response_body = "{\"status\": \"ok\"}";
            status_code = MHD_HTTP_OK;
        } else if (strcmp(url, "/api/v1/fibers/stats/realtime") == 0) {
            response_body = get_realtime_stats();
            status_code = response_body.empty() ? MHD_HTTP_INTERNAL_SERVER_ERROR : MHD_HTTP_OK;
        } else if (strcmp(url, "/api/v1/fibers/colored/all") == 0) {
            response_body = get_all_colored_fibers();
            status_code = response_body.empty() ? MHD_HTTP_INTERNAL_SERVER_ERROR : MHD_HTTP_OK;
        } else if (strncmp(url, "/api/v1/fibers/stats/trend", 26) == 0) {
            const char* start_time = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "start_time");
            const char* end_time = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "end_time");
            response_body = get_stats_trend(start_time ? start_time : "", end_time ? end_time : "");
            status_code = response_body.empty() ? MHD_HTTP_INTERNAL_SERVER_ERROR : MHD_HTTP_OK;
        } else if (strncmp(url, "/api/v1/topology/fibers/", 24) == 0 && strstr(url, "/scene") != nullptr) {
            std::string fiber_id_str = std::string(url + 24);
            size_t scene_pos = fiber_id_str.find("/scene");
            if (scene_pos != std::string::npos) {
                fiber_id_str = fiber_id_str.substr(0, scene_pos);
                response_body = get_fiber_scene(std::stoi(fiber_id_str));
                status_code = response_body.empty() ? MHD_HTTP_INTERNAL_SERVER_ERROR : MHD_HTTP_OK;
            }
        }
    }
    
    struct MHD_Response* response = MHD_create_response_from_buffer(response_body.size(),
                                                                    const_cast<char*>(response_body.c_str()),
                                                                    MHD_RESPMEM_MUST_COPY);
    if (!response) {
        return MHD_NO;
    }
    
    MHD_add_response_header(response, "Content-Type", "application/json");
    MHD_add_response_header(response, "Access-Control-Allow-Origin", "*");
    
    MHD_queue_response(connection, status_code, response);
    MHD_destroy_response(response);
    return MHD_YES;
}

std::string HttpServer::get_realtime_stats() {
    fiber::maint::GetFiberStatsRealtimeRequest req;
    grpc::ClientContext ctx;
    fiber::maint::GetFiberStatsRealtimeResponse resp;
    
    grpc::Status status = fiber_maint_stub_->GetFiberStatsRealtime(&ctx, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("Failed to get stats: {}", status.error_message());
        return "";
    }
    
    std::string json = "{\"total_fibers\": " + std::to_string(resp.total_fibers()) +
                       ", \"red_count\": " + std::to_string(resp.red_count()) +
                       ", \"yellow_count\": " + std::to_string(resp.yellow_count()) +
                       ", \"green_count\": " + std::to_string(resp.green_count()) +
                       ", \"total_colored\": " + std::to_string(resp.red_count() + resp.yellow_count()) +
                       ", \"active_alarms\": " + std::to_string(resp.active_alarms()) + "}";
    return json;
}

std::string HttpServer::get_all_colored_fibers() {
    fiber::maint::GetAllColoredFibersRequest req;
    grpc::ClientContext ctx;
    fiber::maint::GetAllColoredFibersResponse resp;
    
    grpc::Status status = fiber_maint_stub_->GetAllColoredFibers(&ctx, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("Failed to get colored fibers: {}", status.error_message());
        return "";
    }
    
    std::string json = "{\"fibers\": [";
    for (int i = 0; i < resp.fibers_size(); ++i) {
        const auto& cf = resp.fibers(i);
        const auto& f = cf.fiber();
        if (i > 0) json += ",";
        std::string color_str;
        switch (cf.color()) {
            case fiber::common::GREEN: color_str = "GREEN"; break;
            case fiber::common::RED: color_str = "RED"; break;
            case fiber::common::YELLOW: color_str = "YELLOW"; break;
            default: color_str = "UNKNOWN";
        }
        json += "{\"fiber\": {";
        json += "\"fiber_id\": " + std::to_string(f.fiber_id()) + ",";
        json += "\"src_board_id\": " + std::to_string(f.src_board_id()) + ",";
        json += "\"src_port_id\": " + std::to_string(f.src_port_id()) + ",";
        json += "\"src_ne_id\": " + std::to_string(f.src_ne_id()) + ",";
        json += "\"dst_board_id\": " + std::to_string(f.dst_board_id()) + ",";
        json += "\"dst_port_id\": " + std::to_string(f.dst_port_id()) + ",";
        json += "\"dst_ne_id\": " + std::to_string(f.dst_ne_id());
        json += "}, \"color\": \"" + color_str + "\"";
        json += ", \"scenario_type\": " + std::to_string(cf.scene_type());
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_stats_trend(const std::string& start_time, const std::string& end_time) {
    fiber::maint::GetFiberStatsTrendRequest req;
    req.set_start_time(start_time);
    req.set_end_time(end_time);
    
    grpc::ClientContext ctx;
    fiber::maint::GetFiberStatsTrendResponse resp;
    
    grpc::Status status = fiber_maint_stub_->GetFiberStatsTrend(&ctx, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("Failed to get stats trend: {}", status.error_message());
        return "";
    }
    
    std::string json = "{\"points\": [";
    for (int i = 0; i < resp.points_size(); ++i) {
        const auto& point = resp.points(i);
        if (i > 0) json += ",";
        json += "{\"timestamp\": \"" + point.timestamp() + "\"";
        json += ", \"red_count\": " + std::to_string(point.red_count());
        json += ", \"yellow_count\": " + std::to_string(point.yellow_count());
        json += ", \"total_colored\": " + std::to_string(point.total_colored());
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_fiber_scene(int fiber_id) {
    fiber::topology::GetFiberSceneRequest req;
    req.set_inter_ne_fiber_id(fiber_id);
    grpc::ClientContext ctx;
    fiber::topology::GetFiberSceneResponse resp;
    
    grpc::Status status = topology_stub_->GetFiberScene(&ctx, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("Failed to get fiber scene: {}", status.error_message());
        return "";
    }
    
    if (!resp.found()) {
        return "{\"found\": false, \"error_message\": \"" + resp.error_message() + "\"}";
    }
    
    const auto& scene = resp.scene();
    std::string json = "{\"found\": true, \"scene\": {";
    json += "\"scene_type\": "; json += std::to_string(scene.scene_type()); json += ",";
    json += "\"inter_ne_fiber_id\": "; json += std::to_string(scene.inter_ne_fiber_id()); json += ",";
    
    const auto& fiber = scene.inter_ne_fiber();
    json += "\"inter_ne_fiber\": {";
    json += "\"fiber_id\": "; json += std::to_string(fiber.fiber_id()); json += ",";
    json += "\"src_board_id\": "; json += std::to_string(fiber.src_board_id()); json += ",";
    json += "\"src_port_id\": "; json += std::to_string(fiber.src_port_id()); json += ",";
    json += "\"src_ne_id\": "; json += std::to_string(fiber.src_ne_id()); json += ",";
    json += "\"dst_board_id\": "; json += std::to_string(fiber.dst_board_id()); json += ",";
    json += "\"dst_port_id\": "; json += std::to_string(fiber.dst_port_id()); json += ",";
    json += "\"dst_ne_id\": "; json += std::to_string(fiber.dst_ne_id()); json += "},";
    
    if (scene.has_src_active_board()) {
        const auto& board = scene.src_active_board();
        json += "\"src_active_board\": {";
        json += "\"board_id\": "; json += std::to_string(board.board_id()); json += ",";
        json += "\"ne_id\": "; json += std::to_string(board.ne_id()); json += ",";
        json += "\"board_type\": "; json += std::to_string(static_cast<int>(board.board_type())); json += "},";
    }
    
    if (scene.has_dst_active_board()) {
        const auto& board = scene.dst_active_board();
        json += "\"dst_active_board\": {";
        json += "\"board_id\": "; json += std::to_string(board.board_id()); json += ",";
        json += "\"ne_id\": "; json += std::to_string(board.ne_id()); json += ",";
        json += "\"board_type\": "; json += std::to_string(static_cast<int>(board.board_type())); json += "},";
    }
    
    json += "\"ne_internal_fibers\": [";
    for (int i = 0; i < scene.ne_internal_fibers_size(); ++i) {
        const auto& f = scene.ne_internal_fibers(i);
        if (i > 0) json += ",";
        json += "{\"fiber_id\": "; json += std::to_string(f.fiber_id()); json += ",";
        json += "\"src_board_id\": "; json += std::to_string(f.src_board_id()); json += ",";
        json += "\"src_port_id\": "; json += std::to_string(f.src_port_id()); json += ",";
        json += "\"src_ne_id\": "; json += std::to_string(f.src_ne_id()); json += ",";
        json += "\"dst_board_id\": "; json += std::to_string(f.dst_board_id()); json += ",";
        json += "\"dst_port_id\": "; json += std::to_string(f.dst_port_id()); json += ",";
        json += "\"dst_ne_id\": "; json += std::to_string(f.dst_ne_id()); json += "}";
    }
    json += "],";
    
    json += "\"passive_boards\": [";
    for (int i = 0; i < scene.passive_boards_size(); ++i) {
        const auto& board = scene.passive_boards(i);
        if (i > 0) json += ",";
        json += "{\"board_id\": "; json += std::to_string(board.board_id()); json += ",";
        json += "\"ne_id\": "; json += std::to_string(board.ne_id()); json += ",";
        json += "\"board_type\": "; json += std::to_string(static_cast<int>(board.board_type())); json += "}";
    }
    json += "]";
    
    json += "}}";
    return json;
}

void HttpServer::start() {
    daemon_ = MHD_start_daemon(MHD_USE_SELECT_INTERNALLY, port_,
                               nullptr, nullptr,
                               &HttpServer::handle_request, this,
                               MHD_OPTION_END);
    
    if (daemon_) {
        Logger::instance().info("API Gateway HTTP server listening on port: {}", port_);
    } else {
        Logger::instance().error("Failed to start HTTP server on port {}", port_);
    }
}
