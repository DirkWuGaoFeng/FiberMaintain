#include <cerrno>
#include <cstdarg>
#include <cstdio>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <chrono>
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
#include <cstring>
#include <sstream>

// ── 连接状态（POST body 累积） ──
struct ConnectionInfo {
    std::string post_body;
};

// ── 极简 JSON 解析辅助（无第三方依赖） ──
static int json_get_int(const std::string& json, const std::string& key, int def = 0) {
    auto pos = json.find("\"" + key + "\"");
    if (pos == std::string::npos) return def;
    pos = json.find(':', pos);
    if (pos == std::string::npos) return def;
    pos++;
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    return std::stoi(json.substr(pos));
}
static double json_get_double(const std::string& json, const std::string& key, double def = 0.0) {
    auto pos = json.find("\"" + key + "\"");
    if (pos == std::string::npos) return def;
    pos = json.find(':', pos);
    if (pos == std::string::npos) return def;
    pos++;
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) pos++;
    return std::stod(json.substr(pos));
}
static std::string json_get_string(const std::string& json, const std::string& key, const std::string& def = "") {
    auto pos = json.find("\"" + key + "\"");
    if (pos == std::string::npos) return def;
    pos = json.find(':', pos);
    if (pos == std::string::npos) return def;
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) return def;
    auto end = json.find('"', pos + 1);
    if (end == std::string::npos) return def;
    return json.substr(pos + 1, end - pos - 1);
}

// ── 构造 ──
HttpServer::HttpServer() : port_(8080), daemon_(nullptr) {}

HttpServer::~HttpServer() {
    if (daemon_) MHD_stop_daemon(daemon_);
}

bool HttpServer::init(int port) {
    port_ = port;
    auto& cfg = Config::instance();
    std::string board_addr = cfg.get_string("board_service.addr", "localhost:50051");
    std::string topology_addr = cfg.get_string("topology_service.addr", "localhost:50062");
    std::string perf_addr = cfg.get_string("performance_service.addr", "localhost:50053");
    std::string alarm_addr = cfg.get_string("alarm_service.addr", "localhost:50054");
    std::string fiber_maint_addr = cfg.get_string("fiber_maint_service.addr", "localhost:50055");
    
    board_stub_ = fiber::board::BoardService::NewStub(grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials()));
    topology_stub_ = fiber::topology::TopologyService::NewStub(grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials()));
    perf_stub_ = fiber::performance::PerformanceService::NewStub(grpc::CreateChannel(perf_addr, grpc::InsecureChannelCredentials()));
    alarm_stub_ = fiber::alarm::AlarmService::NewStub(grpc::CreateChannel(alarm_addr, grpc::InsecureChannelCredentials()));
    fiber_maint_stub_ = fiber::maint::FiberMaintService::NewStub(grpc::CreateChannel(fiber_maint_addr, grpc::InsecureChannelCredentials()));
    return true;
}

// ── 辅助方法 ──
int HttpServer::extract_id_from_path(const char* url, const char* prefix) {
    size_t plen = strlen(prefix);
    if (strncmp(url, prefix, plen) != 0) return -1;
    const char* rest = url + plen;
    return std::atoi(rest);
}

std::string HttpServer::extract_trailing_path(const char* url, const char* prefix) {
    size_t plen = strlen(prefix);
    if (strncmp(url, prefix, plen) != 0) return "";
    return std::string(url + plen);
}

MHD_Result HttpServer::send_response(struct MHD_Connection* connection,
                                      int status_code, const std::string& body) {
    struct MHD_Response* response = MHD_create_response_from_buffer(
        body.size(), const_cast<char*>(body.c_str()), MHD_RESPMEM_MUST_COPY);
    if (!response) return MHD_NO;
    MHD_add_response_header(response, "Content-Type", "application/json");
    MHD_add_response_header(response, "Access-Control-Allow-Origin", "*");
    MHD_add_response_header(response, "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
    MHD_add_response_header(response, "Access-Control-Allow-Headers", "Content-Type, X-Source, X-Trace-Id, X-User-Role");
    MHD_queue_response(connection, status_code, response);
    MHD_destroy_response(response);
    return MHD_YES;
}

// ── MHD 回调：连接完成时释放 ConnectionInfo ──
void HttpServer::request_completed(void* /*cls*/, struct MHD_Connection* /*connection*/,
                                    void** con_cls, MHD_RequestTerminationCode /*toe*/) {
    if (*con_cls) {
        delete static_cast<ConnectionInfo*>(*con_cls);
        *con_cls = nullptr;
    }
}

// ── MHD 回调：主请求处理 ──
MHD_Result HttpServer::handle_request(void* cls, struct MHD_Connection* connection,
                                       const char* url, const char* method,
                                       const char* /*version*/, const char* upload_data,
                                       size_t* upload_data_size, void** con_cls) {
    // 首次调用：创建连接状态
    if (*con_cls == nullptr) {
        *con_cls = new ConnectionInfo();
        return MHD_YES;
    }
    
    ConnectionInfo* ci = static_cast<ConnectionInfo*>(*con_cls);
    
    // 累积 POST body
    if (*upload_data_size > 0) {
        ci->post_body.append(upload_data, *upload_data_size);
        *upload_data_size = 0;
        return MHD_YES;
    }
    
    HttpServer* server = static_cast<HttpServer*>(cls);
    return server->process_request(connection, url, method, ci->post_body);
}

// ── 路由分发 ──
MHD_Result HttpServer::process_request(struct MHD_Connection* connection,
                                        const char* url, const char* method,
                                        const std::string& post_body) {
    auto t_start = std::chrono::steady_clock::now();
    
    // OPTIONS (CORS preflight)
    if (strcmp(method, "OPTIONS") == 0) {
        return send_response(connection, MHD_HTTP_OK, "");
    }
    
    // 记录请求入口（realtime 接口使用 trace 级别，避免定时调用冲刷日志）
    std::string method_str(method);
    std::string url_str(url);
    bool is_realtime = (url_str == "/api/v1/fibers/stats/realtime");
    if (method_str == "POST" && !post_body.empty()) {
        std::string body_preview = post_body.size() > 200 ? post_body.substr(0, 200) + "..." : post_body;
        if (is_realtime) {
            Logger::instance().trace("[HTTP] --> {} {} body={}", method_str, url_str, body_preview);
        } else {
            Logger::instance().info("[HTTP] --> {} {} body={}", method_str, url_str, body_preview);
        }
    } else {
        if (is_realtime) {
            Logger::instance().trace("[HTTP] --> {} {}", method_str, url_str);
        } else {
            Logger::instance().info("[HTTP] --> {} {}", method_str, url_str);
        }
    }
    
    std::string body;
    int status = MHD_HTTP_NOT_FOUND;
    
    // ═══════════════════════ GET 路由 ═══════════════════════
    if (strcmp(method, "GET") == 0) {
        // ── 健康检查 ──
        if (strcmp(url, "/health") == 0) {
            body = handle_health(); status = MHD_HTTP_OK;
        }
        // ── §2.1 Board ──
        else if (strcmp(url, "/api/v1/boards") == 0) {
            body = list_boards();
            status = body.empty() ? 500 : 200;
        }
        else if (strncmp(url, "/api/v1/boards/", 15) == 0) {
            // GET /api/v1/boards/{board_id}/fibers
            std::string trailing = extract_trailing_path(url, "/api/v1/boards/");
            auto slash = trailing.find('/');
            if (slash != std::string::npos && trailing.substr(slash) == "/fibers") {
                int bid = std::stoi(trailing.substr(0, slash));
                body = get_board_fibers(bid);
                status = body.empty() ? 500 : 200;
            } else {
                // GET /api/v1/boards/{board_id}
                int bid = std::stoi(trailing);
                body = get_board(bid);
                status = body.empty() ? 500 : 200;
            }
        }
        // ── §2.2 Topology ──
        else if (strcmp(url, "/api/v1/topology/fibers/by_port") == 0) {
            int bid = 0, pid = 0;
            const char* bv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "board_id");
            const char* pv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "port_id");
            if (bv) bid = std::atoi(bv);
            if (pv) pid = std::atoi(pv);
            body = get_fibers_by_port(bid, pid);
            status = body.empty() ? 500 : 200;
        }
        else if (strncmp(url, "/api/v1/topology/fibers/", 24) == 0) {
            std::string trailing = extract_trailing_path(url, "/api/v1/topology/fibers/");
            if (trailing.find("/scene") != std::string::npos) {
                int fid = std::stoi(trailing.substr(0, trailing.find("/scene")));
                body = get_fiber_scene(fid);
                status = body.empty() ? 500 : 200;
            } else {
                int fid = std::stoi(trailing);
                body = get_fiber(fid);
                status = body.empty() ? 500 : 200;
            }
        }
        // ── §2.3 Performance ──
        else if (strcmp(url, "/api/v1/performance/current") == 0) {
            int bid = 0, pid = 0;
            const char* bv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "board_id");
            const char* pv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "port_id");
            if (bv) bid = std::atoi(bv);
            if (pv) pid = std::atoi(pv);
            body = get_current_performance(bid, pid);
            status = body.empty() ? 500 : 200;
        }
        else if (strcmp(url, "/api/v1/performance/history") == 0) {
            int bid = 0, pid = 0;
            const char* bv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "board_id");
            const char* pv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "port_id");
            const char* st = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "start_time");
            const char* et = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "end_time");
            if (bv) bid = std::atoi(bv);
            if (pv) pid = std::atoi(pv);
            body = get_history_performance(bid, pid, st ? st : "", et ? et : "");
            status = body.empty() ? 500 : 200;
        }
        // ── §2.4 Alarm ──
        else if (strcmp(url, "/api/v1/alarms/current") == 0) {
            int bid = 0, pid = 0;
            const char* bv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "board_id");
            const char* pv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "port_id");
            if (bv) bid = std::atoi(bv);
            if (pv) pid = std::atoi(pv);
            body = get_current_alarms(bid, pid);
            status = body.empty() ? 500 : 200;
        }
        // ── §2.5 FiberMaint ──
        else if (strncmp(url, "/api/v1/fibers/", 15) == 0) {
            std::string trailing = extract_trailing_path(url, "/api/v1/fibers/");
            if (trailing == "stats/realtime") {
                body = get_realtime_stats();
                status = body.empty() ? 500 : 200;
            } else if (strncmp(trailing.c_str(), "stats/trend", 11) == 0) {
                const char* st = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "start_time");
                const char* et = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "end_time");
                body = get_stats_trend(st ? st : "", et ? et : "");
                status = body.empty() ? 500 : 200;
            } else if (trailing == "colored/all") {
                body = get_all_colored_fibers();
                status = body.empty() ? 500 : 200;
            } else if (trailing == "colored") {
                const char* cv = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "color");
                body = get_colored_fibers(cv ? cv : "RED");
                status = body.empty() ? 500 : 200;
            } else {
                // /api/v1/fibers/{id}/performance or /api/v1/fibers/{id}/spanloss
                auto slash = trailing.find('/');
                if (slash != std::string::npos) {
                    int fid = std::stoi(trailing.substr(0, slash));
                    std::string sub = trailing.substr(slash + 1);
                    if (sub == "performance/history") {
                        const char* st = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "start_time");
                        const char* et = MHD_lookup_connection_value(connection, MHD_GET_ARGUMENT_KIND, "end_time");
                        body = get_fiber_history_performance(fid, st ? st : "", et ? et : "");
                        status = body.empty() ? 500 : 200;
                    } else if (sub == "performance") {
                        body = get_fiber_performance(fid);
                        status = body.empty() ? 500 : 200;
                    } else if (sub == "spanloss") {
                        body = get_fiber_spanloss(fid);
                        status = body.empty() ? 500 : 200;
                    }
                }
            }
        }
    }
    // ═══════════════════════ POST 路由 ═══════════════════════
    else if (strcmp(method, "POST") == 0) {
        if (strcmp(url, "/api/v1/boards") == 0) {
            body = post_create_board(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/boards/batch") == 0) {
            body = post_batch_boards(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/topology/fibers") == 0) {
            body = post_create_fiber(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/topology/fibers/batch") == 0) {
            body = post_batch_fibers(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/performance/report") == 0) {
            body = post_report_performance(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/performance/current/batch") == 0) {
            body = post_batch_current_performance(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/performance/history/batch") == 0) {
            body = post_batch_history_performance(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/alarms/report") == 0) {
            body = post_report_alarm(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/alarms/clear") == 0) {
            body = post_clear_alarm(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/alarms/current/batch") == 0) {
            body = post_batch_current_alarms(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/fibers/performance/batch") == 0) {
            body = post_batch_fiber_performance(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/fibers/performance/history/batch") == 0) {
            body = post_batch_fiber_history_performance(post_body); status = body.empty() ? 500 : 200;
        } else if (strcmp(url, "/api/v1/fibers/spanloss/batch") == 0) {
            body = post_batch_fiber_spanloss(post_body); status = body.empty() ? 500 : 200;
        }
    }
    // ═══════════════════════ DELETE 路由 ═══════════════════════
    else if (strcmp(method, "DELETE") == 0) {
        if (strncmp(url, "/api/v1/boards/", 15) == 0) {
            int bid = extract_id_from_path(url, "/api/v1/boards/");
            body = delete_board(bid); status = body.empty() ? 500 : 200;
        } else if (strncmp(url, "/api/v1/topology/fibers/", 24) == 0) {
            int fid = extract_id_from_path(url, "/api/v1/topology/fibers/");
            body = delete_fiber(fid); status = body.empty() ? 500 : 200;
        }
    }
    
    if (body.empty() && status == MHD_HTTP_NOT_FOUND) {
        body = "{\"error\": \"not found\", \"path\": \"" + std::string(url) + "\"}";
    }
    
    // 记录响应出口（realtime 接口使用 trace 级别）
    auto t_end = std::chrono::steady_clock::now();
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(t_end - t_start).count();
    std::string summary = "size=" + std::to_string(body.size()) + " elapsed=" + std::to_string(elapsed_ms) + "ms";
    if (status >= 400) {
        Logger::instance().warn("[HTTP] <-- {} {} status={} {}",
                                method_str, url_str, status, summary);
    } else {
        if (is_realtime) {
            Logger::instance().trace("[HTTP] <-- {} {} status={} {}",
                                     method_str, url_str, status, summary);
        } else {
            Logger::instance().info("[HTTP] <-- {} {} status={} {}",
                                     method_str, url_str, status, summary);
        }
    }
    return send_response(connection, status, body);
}

// ═══════════════════════════════════════════════════════════
//  Handler 实现
// ═══════════════════════════════════════════════════════════

std::string HttpServer::handle_health() {
    return "{\"status\": \"ok\"}";
}

// ── §2.1 BoardService ──

std::string HttpServer::post_create_board(const std::string& body) {
    Logger::instance().info("[gRPC] CreateBoard request");
    fiber::board::CreateBoardRequest req;
    req.set_board_id(json_get_int(body, "board_id"));
    req.set_board_type(static_cast<fiber::common::BoardType>(json_get_int(body, "board_type")));
    req.set_ne_id(json_get_int(body, "ne_id"));
    grpc::ClientContext ctx;
    fiber::board::CreateBoardResponse resp;
    auto st = board_stub_->CreateBoard(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] CreateBoard failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] CreateBoard success={}", resp.success());
    return "{\"success\": " + std::string(resp.success() ? "true" : "false") +
           ", \"message\": \"" + resp.message() + "\"}";
}

std::string HttpServer::delete_board(int board_id) {
    Logger::instance().info("[gRPC] DeleteBoard board_id={}", board_id);
    fiber::board::DeleteBoardRequest req;
    req.set_board_id(board_id);
    grpc::ClientContext ctx;
    fiber::board::DeleteBoardResponse resp;
    auto st = board_stub_->DeleteBoard(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] DeleteBoard failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] DeleteBoard success={} deleted_fibers={}", resp.success(), resp.deleted_fiber_ids_size());
    std::string json = "{\"success\": " + std::string(resp.success() ? "true" : "false") +
                       ", \"message\": \"" + resp.message() + "\"" +
                       ", \"deleted_fiber_ids\": [";
    for (int i = 0; i < resp.deleted_fiber_ids_size(); ++i) {
        if (i > 0) json += ",";
        json += std::to_string(resp.deleted_fiber_ids(i));
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_board(int board_id) {
    Logger::instance().info("[gRPC] GetBoard board_id={}", board_id);
    fiber::board::GetBoardRequest req;
    req.set_board_id(board_id);
    grpc::ClientContext ctx;
    fiber::board::GetBoardResponse resp;
    auto st = board_stub_->GetBoard(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetBoard failed: {}", st.error_message()); return ""; }
    if (!resp.has_board()) { Logger::instance().info("[gRPC] GetBoard not found"); return "{\"found\": false}"; }
    Logger::instance().info("[gRPC] GetBoard found board_id={} ne_id={} ports={}", resp.board().board_id(), resp.board().ne_id(), resp.board().ports_size());
    const auto& b = resp.board();
    std::string json = "{\"board\": {\"board_id\": " + std::to_string(b.board_id()) +
                       ", \"board_type\": " + std::to_string(static_cast<int>(b.board_type())) +
                       ", \"ne_id\": " + std::to_string(b.ne_id()) +
                       ", \"ports\": [";
    for (int i = 0; i < b.ports_size(); ++i) {
        if (i > 0) json += ",";
        json += "{\"port_id\": " + std::to_string(b.ports(i).port_id()) +
                ", \"occupied\": " + std::string(b.ports(i).occupied() ? "true" : "false") + "}";
    }
    json += "]}}";
    return json;
}

std::string HttpServer::post_batch_boards(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetBoards request");
    fiber::board::BatchGetBoardsRequest req;
    // 简易解析 {"board_ids": [1,2,3]}
    auto pos = body.find('[');
    if (pos != std::string::npos) {
        auto end = body.find(']', pos);
        std::string ids_str = body.substr(pos + 1, end - pos - 1);
        std::istringstream ss(ids_str);
        std::string tok;
        while (std::getline(ss, tok, ',')) {
            int v = std::atoi(tok.c_str());
            if (v != 0) req.add_board_ids(v);
        }
    }
    grpc::ClientContext ctx;
    fiber::board::BatchGetBoardsResponse resp;
    auto st = board_stub_->BatchGetBoards(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetBoards failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetBoards results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"found\": " + std::string(r.found() ? "true" : "false");
        if (r.found() && r.has_board()) {
            const auto& b = r.board();
            json += ", \"board\": {\"board_id\": " + std::to_string(b.board_id()) +
                    ", \"board_type\": " + std::to_string(static_cast<int>(b.board_type())) +
                    ", \"ne_id\": " + std::to_string(b.ne_id()) + "}";
        }
        if (!r.error_message().empty())
            json += ", \"error_message\": \"" + r.error_message() + "\"";
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_board_fibers(int board_id) {
    Logger::instance().info("[gRPC] GetBoardFibers board_id={}", board_id);
    fiber::board::GetBoardFibersRequest req;
    req.set_board_id(board_id);
    grpc::ClientContext ctx;
    fiber::board::GetBoardFibersResponse resp;
    auto st = board_stub_->GetBoardFibers(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetBoardFibers failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetBoardFibers count={}", resp.fibers_size());
    std::string json = "{\"fibers\": [";
    for (int i = 0; i < resp.fibers_size(); ++i) {
        const auto& f = resp.fibers(i);
        if (i > 0) json += ",";
        json += "{\"fiber_id\": " + std::to_string(f.fiber_id()) +
                ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
                ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
                ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
                ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
                ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
                ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::list_boards() {
    Logger::instance().info("[gRPC] ListBoards request");
    fiber::board::ListBoardsRequest req;
    grpc::ClientContext ctx;
    fiber::board::ListBoardsResponse resp;
    auto st = board_stub_->ListBoards(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] ListBoards failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] ListBoards count={}", resp.boards_size());
    std::string json = "{\"boards\": [";
    for (int i = 0; i < resp.boards_size(); ++i) {
        const auto& b = resp.boards(i);
        if (i > 0) json += ",";
        json += "{\"board_id\": " + std::to_string(b.board_id()) +
                ", \"board_type\": " + std::to_string(static_cast<int>(b.board_type())) +
                ", \"ne_id\": " + std::to_string(b.ne_id()) +
                ", \"ports\": [";
        for (int j = 0; j < b.ports_size(); ++j) {
            if (j > 0) json += ",";
            json += "{\"port_id\": " + std::to_string(b.ports(j).port_id()) +
                    ", \"occupied\": " + std::string(b.ports(j).occupied() ? "true" : "false") + "}";
        }
        json += "]}";
    }
    json += "]}";
    return json;
}

// ── §2.2 TopologyService ──

std::string HttpServer::post_create_fiber(const std::string& body) {
    Logger::instance().info("[gRPC] CreateFiber request");
    fiber::topology::CreateFiberRequest req;
    req.set_src_board_id(json_get_int(body, "src_board_id"));
    req.set_src_port_id(json_get_int(body, "src_port_id"));
    req.set_dst_board_id(json_get_int(body, "dst_board_id"));
    req.set_dst_port_id(json_get_int(body, "dst_port_id"));
    grpc::ClientContext ctx;
    fiber::topology::CreateFiberResponse resp;
    auto st = topology_stub_->CreateFiber(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] CreateFiber failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] CreateFiber success={} fiber_id={}", resp.success(), resp.fiber_id());
    return "{\"success\": " + std::string(resp.success() ? "true" : "false") +
           ", \"fiber_id\": " + std::to_string(resp.fiber_id()) +
           ", \"message\": \"" + resp.message() + "\"}";
}

std::string HttpServer::delete_fiber(int fiber_id) {
    Logger::instance().info("[gRPC] DeleteFiber fiber_id={}", fiber_id);
    fiber::topology::DeleteFiberRequest req;
    req.set_fiber_id(fiber_id);
    grpc::ClientContext ctx;
    fiber::topology::DeleteFiberResponse resp;
    auto st = topology_stub_->DeleteFiber(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] DeleteFiber failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] DeleteFiber success={}", resp.success());
    return "{\"success\": " + std::string(resp.success() ? "true" : "false") +
           ", \"message\": \"" + resp.message() + "\"}";
}

std::string HttpServer::get_fiber(int fiber_id) {
    Logger::instance().info("[gRPC] GetFiber fiber_id={}", fiber_id);
    fiber::topology::GetFiberRequest req;
    req.set_fiber_id(fiber_id);
    grpc::ClientContext ctx;
    fiber::topology::GetFiberResponse resp;
    auto st = topology_stub_->GetFiber(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiber failed: {}", st.error_message()); return ""; }
    if (!resp.has_fiber()) { Logger::instance().info("[gRPC] GetFiber not found"); return "{\"found\": false}"; }
    const auto& f = resp.fiber();
    return "{\"fiber\": {\"fiber_id\": " + std::to_string(f.fiber_id()) +
           ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
           ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
           ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
           ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
           ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
           ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}}";
}

std::string HttpServer::post_batch_fibers(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetFibers request");
    fiber::topology::BatchGetFibersRequest req;
    auto pos = body.find('[');
    if (pos != std::string::npos) {
        auto end = body.find(']', pos);
        std::string ids_str = body.substr(pos + 1, end - pos - 1);
        std::istringstream ss(ids_str);
        std::string tok;
        while (std::getline(ss, tok, ',')) {
            int v = std::atoi(tok.c_str());
            if (v != 0) req.add_fiber_ids(v);
        }
    }
    grpc::ClientContext ctx;
    fiber::topology::BatchGetFibersResponse resp;
    auto st = topology_stub_->BatchGetFibers(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetFibers failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetFibers results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"found\": " + std::string(r.found() ? "true" : "false");
        if (r.found() && r.has_fiber()) {
            const auto& f = r.fiber();
            json += ", \"fiber\": {\"fiber_id\": " + std::to_string(f.fiber_id()) +
                    ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
                    ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
                    ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
                    ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
                    ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
                    ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}";
        }
        if (!r.error_message().empty())
            json += ", \"error_message\": \"" + r.error_message() + "\"";
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_fiber_scene(int fiber_id) {
    Logger::instance().info("[gRPC] GetFiberScene fiber_id={}", fiber_id);
    fiber::topology::GetFiberSceneRequest req;
    req.set_inter_ne_fiber_id(fiber_id);
    grpc::ClientContext ctx;
    fiber::topology::GetFiberSceneResponse resp;
    auto st = topology_stub_->GetFiberScene(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiberScene failed: {}", st.error_message()); return ""; }
    if (!resp.found()) { Logger::instance().info("[gRPC] GetFiberScene not found"); return "{\"found\": false, \"error_message\": \"" + resp.error_message() + "\"}"; }
    const auto& scene = resp.scene();
    std::string json = "{\"found\": true, \"scene\": {";
    json += "\"scene_type\": " + std::to_string(scene.scene_type()) + ",";
    json += "\"inter_ne_fiber_id\": " + std::to_string(scene.inter_ne_fiber_id()) + ",";
    const auto& fiber = scene.inter_ne_fiber();
    json += "\"inter_ne_fiber\": {\"fiber_id\": " + std::to_string(fiber.fiber_id()) +
            ", \"src_board_id\": " + std::to_string(fiber.src_board_id()) +
            ", \"src_port_id\": " + std::to_string(fiber.src_port_id()) +
            ", \"src_ne_id\": " + std::to_string(fiber.src_ne_id()) +
            ", \"dst_board_id\": " + std::to_string(fiber.dst_board_id()) +
            ", \"dst_port_id\": " + std::to_string(fiber.dst_port_id()) +
            ", \"dst_ne_id\": " + std::to_string(fiber.dst_ne_id()) + "},";
    if (scene.has_src_active_board()) {
        const auto& b = scene.src_active_board();
        json += "\"src_active_board\": {\"board_id\": " + std::to_string(b.board_id()) +
                ", \"ne_id\": " + std::to_string(b.ne_id()) +
                ", \"board_type\": " + std::to_string(static_cast<int>(b.board_type())) + "},";
    }
    if (scene.has_dst_active_board()) {
        const auto& b = scene.dst_active_board();
        json += "\"dst_active_board\": {\"board_id\": " + std::to_string(b.board_id()) +
                ", \"ne_id\": " + std::to_string(b.ne_id()) +
                ", \"board_type\": " + std::to_string(static_cast<int>(b.board_type())) + "},";
    }
    json += "\"ne_internal_fibers\": [";
    for (int i = 0; i < scene.ne_internal_fibers_size(); ++i) {
        const auto& f = scene.ne_internal_fibers(i);
        if (i > 0) json += ",";
        json += "{\"fiber_id\": " + std::to_string(f.fiber_id()) +
                ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
                ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
                ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
                ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
                ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
                ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}";
    }
    json += "],\"passive_boards\": [";
    for (int i = 0; i < scene.passive_boards_size(); ++i) {
        const auto& b = scene.passive_boards(i);
        if (i > 0) json += ",";
        json += "{\"board_id\": " + std::to_string(b.board_id()) +
                ", \"ne_id\": " + std::to_string(b.ne_id()) +
                ", \"board_type\": " + std::to_string(static_cast<int>(b.board_type())) + "}";
    }
    json += "]}}";
    return json;
}

std::string HttpServer::get_fibers_by_port(int board_id, int port_id) {
    Logger::instance().info("[gRPC] GetFibersByPort board_id={} port_id={}", board_id, port_id);
    fiber::topology::GetFibersByPortRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    grpc::ClientContext ctx;
    fiber::topology::GetFibersByPortResponse resp;
    auto st = topology_stub_->GetFibersByPort(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFibersByPort failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetFibersByPort count={}", resp.fibers_size());
    std::string json = "{\"fibers\": [";
    for (int i = 0; i < resp.fibers_size(); ++i) {
        const auto& f = resp.fibers(i);
        if (i > 0) json += ",";
        json += "{\"fiber_id\": " + std::to_string(f.fiber_id()) +
                ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
                ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
                ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
                ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
                ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
                ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}";
    }
    json += "]}";
    return json;
}

// ── §2.3 PerformanceService ──

std::string HttpServer::post_report_performance(const std::string& body) {
    Logger::instance().info("[gRPC] ReportPerformance request");
    fiber::performance::ReportPerformanceRequest req;
    req.set_board_id(json_get_int(body, "board_id"));
    req.set_port_id(json_get_int(body, "port_id"));
    req.set_oop_value(json_get_double(body, "oop_value"));
    req.set_iop_value(json_get_double(body, "iop_value"));
    grpc::ClientContext ctx;
    fiber::performance::ReportPerformanceResponse resp;
    auto st = perf_stub_->ReportPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] ReportPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] ReportPerformance success={}", resp.success());
    return "{\"success\": " + std::string(resp.success() ? "true" : "false") +
           ", \"message\": \"" + resp.message() + "\"}";
}

std::string HttpServer::get_current_performance(int board_id, int port_id) {
    Logger::instance().info("[gRPC] GetCurrentPerformance board_id={} port_id={}", board_id, port_id);
    fiber::performance::GetCurrentPerformanceRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    grpc::ClientContext ctx;
    fiber::performance::GetCurrentPerformanceResponse resp;
    auto st = perf_stub_->GetCurrentPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetCurrentPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetCurrentPerformance oop={} iop={}", resp.oop_value(), resp.iop_value());
    return "{\"board_id\": " + std::to_string(resp.board_id()) +
           ", \"port_id\": " + std::to_string(resp.port_id()) +
           ", \"oop_value\": " + std::to_string(resp.oop_value()) +
           ", \"iop_value\": " + std::to_string(resp.iop_value()) +
           ", \"updated_at\": \"" + resp.updated_at() + "\"}";
}

std::string HttpServer::get_history_performance(int board_id, int port_id,
                                                  const std::string& start_time,
                                                  const std::string& end_time) {
    Logger::instance().info("[gRPC] GetHistoryPerformance board_id={} port_id={} start={} end={}", board_id, port_id, start_time.c_str(), end_time.c_str());
    fiber::performance::GetHistoryPerformanceRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    req.set_start_time(start_time);
    req.set_end_time(end_time);
    grpc::ClientContext ctx;
    fiber::performance::GetHistoryPerformanceResponse resp;
    auto st = perf_stub_->GetHistoryPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetHistoryPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetHistoryPerformance records={}", resp.records_size());
    std::string json = "{\"records\": [";
    for (int i = 0; i < resp.records_size(); ++i) {
        const auto& r = resp.records(i);
        if (i > 0) json += ",";
        json += "{\"recorded_at\": \"" + r.recorded_at() + "\"" +
                ", \"oop_value\": " + std::to_string(r.oop_value()) +
                ", \"iop_value\": " + std::to_string(r.iop_value()) + "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::post_batch_current_performance(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetCurrentPerformance request");
    fiber::performance::BatchGetCurrentPerformanceRequest req;
    // 解析 {"ports": [{"board_id":1,"port_id":1}, ...]}
    size_t pos = 0;
    while ((pos = body.find("\"board_id\"", pos)) != std::string::npos) {
        auto* port = req.add_ports();
        port->set_board_id(json_get_int(body.substr(pos), "board_id"));
        port->set_port_id(json_get_int(body.substr(pos), "port_id"));
        pos += 10;
    }
    grpc::ClientContext ctx;
    fiber::performance::BatchGetCurrentPerformanceResponse resp;
    auto st = perf_stub_->BatchGetCurrentPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetCurrentPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetCurrentPerformance results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"found\": " + std::string(r.found() ? "true" : "false") +
                ", \"board_id\": " + std::to_string(r.board_id()) +
                ", \"port_id\": " + std::to_string(r.port_id());
        if (r.found()) {
            json += ", \"oop_value\": " + std::to_string(r.oop_value()) +
                    ", \"iop_value\": " + std::to_string(r.iop_value());
        }
        if (!r.error_message().empty())
            json += ", \"error_message\": \"" + r.error_message() + "\"";
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::post_batch_history_performance(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetHistoryPerformance request");
    fiber::performance::BatchGetHistoryPerformanceRequest req;
    std::string start_time = json_get_string(body, "start_time");
    std::string end_time = json_get_string(body, "end_time");
    req.set_start_time(start_time);
    req.set_end_time(end_time);
    size_t pos = 0;
    while ((pos = body.find("\"board_id\"", pos)) != std::string::npos) {
        auto* port = req.add_ports();
        port->set_board_id(json_get_int(body.substr(pos), "board_id"));
        port->set_port_id(json_get_int(body.substr(pos), "port_id"));
        pos += 10;
    }
    grpc::ClientContext ctx;
    fiber::performance::BatchGetHistoryPerformanceResponse resp;
    auto st = perf_stub_->BatchGetHistoryPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetHistoryPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetHistoryPerformance results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"board_id\": " + std::to_string(r.board_id()) +
                ", \"port_id\": " + std::to_string(r.port_id()) +
                ", \"records\": [";
        for (int j = 0; j < r.records_size(); ++j) {
            const auto& rec = r.records(j);
            if (j > 0) json += ",";
            json += "{\"recorded_at\": \"" + rec.recorded_at() + "\"" +
                    ", \"oop_value\": " + std::to_string(rec.oop_value()) +
                    ", \"iop_value\": " + std::to_string(rec.iop_value()) + "}";
        }
        json += "]}";
    }
    json += "]}";
    return json;
}

// ── §2.4 AlarmService ──

std::string HttpServer::post_report_alarm(const std::string& body) {
    Logger::instance().info("[gRPC] ReportAlarm request");
    fiber::alarm::ReportAlarmRequest req;
    req.set_board_id(json_get_int(body, "board_id"));
    req.set_port_id(json_get_int(body, "port_id"));
    req.set_alarm_level(static_cast<fiber::common::AlarmLevel>(json_get_int(body, "alarm_level")));
    grpc::ClientContext ctx;
    fiber::alarm::ReportAlarmResponse resp;
    auto st = alarm_stub_->ReportAlarm(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] ReportAlarm failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] ReportAlarm success={}", resp.success());
    return "{\"success\": " + std::string(resp.success() ? "true" : "false") +
           ", \"message\": \"" + resp.message() + "\"}";
}

std::string HttpServer::post_clear_alarm(const std::string& body) {
    Logger::instance().info("[gRPC] ClearAlarm request");
    fiber::alarm::ClearAlarmRequest req;
    req.set_board_id(json_get_int(body, "board_id"));
    req.set_port_id(json_get_int(body, "port_id"));
    req.set_alarm_level(static_cast<fiber::common::AlarmLevel>(json_get_int(body, "alarm_level")));
    grpc::ClientContext ctx;
    fiber::alarm::ClearAlarmResponse resp;
    auto st = alarm_stub_->ClearAlarm(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] ClearAlarm failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] ClearAlarm success={}", resp.success());
    return "{\"success\": " + std::string(resp.success() ? "true" : "false") +
           ", \"message\": \"" + resp.message() + "\"}";
}

std::string HttpServer::get_current_alarms(int board_id, int port_id) {
    Logger::instance().info("[gRPC] GetCurrentAlarms board_id={} port_id={}", board_id, port_id);
    fiber::alarm::GetCurrentAlarmRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    grpc::ClientContext ctx;
    fiber::alarm::GetCurrentAlarmResponse resp;
    auto st = alarm_stub_->GetCurrentAlarm(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetCurrentAlarms failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetCurrentAlarms count={}", resp.alarms_size());
    std::string json = "{\"alarms\": [";
    for (int i = 0; i < resp.alarms_size(); ++i) {
        const auto& a = resp.alarms(i);
        if (i > 0) json += ",";
        std::string level_str;
        switch (a.alarm_level()) {
            case fiber::common::CRITICAL: level_str = "CRITICAL"; break;
            case fiber::common::MINOR: level_str = "MINOR"; break;
            default: level_str = "UNSPECIFIED";
        }
        json += "{\"board_id\": " + std::to_string(a.board_id()) +
                ", \"port_id\": " + std::to_string(a.port_id()) +
                ", \"alarm_level\": \"" + level_str + "\"" +
                ", \"raised_at\": \"" + a.raised_at() + "\"}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::post_batch_current_alarms(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetCurrentAlarms request");
    fiber::alarm::BatchGetCurrentAlarmsRequest req;
    // 解析 {"ports": [{"board_id":1,"port_id":1}, ...]}
    size_t pos = 0;
    while ((pos = body.find("\"board_id\"", pos)) != std::string::npos) {
        auto* port = req.add_ports();
        port->set_board_id(json_get_int(body.substr(pos), "board_id"));
        port->set_port_id(json_get_int(body.substr(pos), "port_id"));
        pos += 10;
    }
    grpc::ClientContext ctx;
    fiber::alarm::BatchGetCurrentAlarmsResponse resp;
    auto st = alarm_stub_->BatchGetCurrentAlarms(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetCurrentAlarms failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetCurrentAlarms results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"board_id\": " + std::to_string(r.board_id()) +
                ", \"port_id\": " + std::to_string(r.port_id()) +
                ", \"alarms\": [";
        for (int j = 0; j < r.alarms_size(); ++j) {
            const auto& a = r.alarms(j);
            if (j > 0) json += ",";
            std::string level_str;
            switch (a.alarm_level()) {
                case fiber::common::CRITICAL: level_str = "CRITICAL"; break;
                case fiber::common::MINOR: level_str = "MINOR"; break;
                default: level_str = "UNSPECIFIED";
            }
            json += "{\"board_id\": " + std::to_string(a.board_id()) +
                    ", \"port_id\": " + std::to_string(a.port_id()) +
                    ", \"alarm_level\": \"" + level_str + "\"" +
                    ", \"raised_at\": \"" + a.raised_at() + "\"}";
        }
        json += "]}";
    }
    json += "]}";
    return json;
}

// ── §2.5 FiberMaintService ──

std::string HttpServer::get_fiber_performance(int fiber_id) {
    Logger::instance().info("[gRPC] GetFiberPerformance fiber_id={}", fiber_id);
    fiber::maint::GetFiberPerformanceRequest req;
    req.set_fiber_id(fiber_id);
    grpc::ClientContext ctx;
    fiber::maint::GetFiberPerformanceResponse resp;
    auto st = fiber_maint_stub_->GetFiberPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiberPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetFiberPerformance src_oop={} dst_iop={} err={}", resp.src_oop(), resp.dst_iop(), resp.error_code());
    return "{\"fiber_id\": " + std::to_string(resp.fiber_id()) +
           ", \"src_oop\": " + std::to_string(resp.src_oop()) +
           ", \"dst_iop\": " + std::to_string(resp.dst_iop()) +
           ", \"error_code\": " + std::to_string(resp.error_code()) +
           ", \"error_message\": \"" + resp.error_message() + "\"}";
}

std::string HttpServer::post_batch_fiber_performance(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetFiberPerformance request");
    fiber::maint::BatchGetFiberPerformanceRequest req;
    auto pos = body.find('[');
    if (pos != std::string::npos) {
        auto end = body.find(']', pos);
        std::string ids_str = body.substr(pos + 1, end - pos - 1);
        std::istringstream ss(ids_str);
        std::string tok;
        while (std::getline(ss, tok, ',')) {
            int v = std::atoi(tok.c_str());
            if (v != 0) req.add_fiber_ids(v);
        }
    }
    grpc::ClientContext ctx;
    fiber::maint::BatchGetFiberPerformanceResponse resp;
    auto st = fiber_maint_stub_->BatchGetFiberPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetFiberPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetFiberPerformance results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"found\": " + std::string(r.found() ? "true" : "false") +
                ", \"fiber_id\": " + std::to_string(r.fiber_id());
        if (r.found()) {
            json += ", \"src_oop\": " + std::to_string(r.src_oop()) +
                    ", \"dst_iop\": " + std::to_string(r.dst_iop());
        }
        json += ", \"error_code\": " + std::to_string(r.error_code());
        if (!r.error_message().empty())
            json += ", \"error_message\": \"" + r.error_message() + "\"";
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_fiber_history_performance(int fiber_id, const std::string& start_time, const std::string& end_time) {
    Logger::instance().info("[gRPC] GetFiberHistoryPerformance fiber_id={} start={} end={}", fiber_id, start_time.c_str(), end_time.c_str());
    fiber::maint::GetFiberHistoryPerformanceRequest req;
    req.set_fiber_id(fiber_id);
    req.set_start_time(start_time);
    req.set_end_time(end_time);
    grpc::ClientContext ctx;
    fiber::maint::GetFiberHistoryPerformanceResponse resp;
    auto st = fiber_maint_stub_->GetFiberHistoryPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiberHistoryPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetFiberHistoryPerformance records={}", resp.records_size());
    std::string json = "{\"fiber_id\": " + std::to_string(fiber_id) + ", \"records\": [";
    for (int i = 0; i < resp.records_size(); ++i) {
        const auto& r = resp.records(i);
        if (i > 0) json += ",";
        json += "{\"recorded_at\": \"" + r.recorded_at() + "\"" +
                ", \"src_oop\": " + std::to_string(r.src_oop()) +
                ", \"dst_iop\": " + std::to_string(r.dst_iop()) + "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::post_batch_fiber_history_performance(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetFiberHistoryPerformance request");
    fiber::maint::BatchGetFiberHistoryPerformanceRequest req;
    req.set_start_time(json_get_string(body, "start_time"));
    req.set_end_time(json_get_string(body, "end_time"));
    auto pos = body.find('[');
    if (pos != std::string::npos) {
        auto end = body.find(']', pos);
        std::string ids_str = body.substr(pos + 1, end - pos - 1);
        std::istringstream ss(ids_str);
        std::string tok;
        while (std::getline(ss, tok, ',')) {
            int v = std::atoi(tok.c_str());
            if (v != 0) req.add_fiber_ids(v);
        }
    }
    grpc::ClientContext ctx;
    fiber::maint::BatchGetFiberHistoryPerformanceResponse resp;
    auto st = fiber_maint_stub_->BatchGetFiberHistoryPerformance(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetFiberHistoryPerformance failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetFiberHistoryPerformance results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"fiber_id\": " + std::to_string(r.fiber_id()) +
                ", \"records\": [";
        for (int j = 0; j < r.records_size(); ++j) {
            const auto& rec = r.records(j);
            if (j > 0) json += ",";
            json += "{\"recorded_at\": \"" + rec.recorded_at() + "\"" +
                    ", \"src_oop\": " + std::to_string(rec.src_oop()) +
                    ", \"dst_iop\": " + std::to_string(rec.dst_iop()) + "}";
        }
        json += "]";
        json += ", \"error_code\": " + std::to_string(r.error_code());
        if (!r.error_message().empty())
            json += ", \"error_message\": \"" + r.error_message() + "\"";
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_fiber_spanloss(int fiber_id) {
    Logger::instance().info("[gRPC] GetFiberSpanloss fiber_id={}", fiber_id);
    fiber::maint::GetFiberSpanlossRequest req;
    req.set_fiber_id(fiber_id);
    grpc::ClientContext ctx;
    fiber::maint::GetFiberSpanlossResponse resp;
    auto st = fiber_maint_stub_->GetFiberSpanloss(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiberSpanloss failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetFiberSpanloss spanloss={}", resp.spanloss());
    return "{\"fiber_id\": " + std::to_string(resp.fiber_id()) +
           ", \"spanloss\": " + std::to_string(resp.spanloss()) + "}";
}

std::string HttpServer::post_batch_fiber_spanloss(const std::string& body) {
    Logger::instance().info("[gRPC] BatchGetFiberSpanloss request");
    fiber::maint::BatchGetFiberSpanlossRequest req;
    auto pos = body.find('[');
    if (pos != std::string::npos) {
        auto end = body.find(']', pos);
        std::string ids_str = body.substr(pos + 1, end - pos - 1);
        std::istringstream ss(ids_str);
        std::string tok;
        while (std::getline(ss, tok, ',')) {
            int v = std::atoi(tok.c_str());
            if (v != 0) req.add_fiber_ids(v);
        }
    }
    grpc::ClientContext ctx;
    fiber::maint::BatchGetFiberSpanlossResponse resp;
    auto st = fiber_maint_stub_->BatchGetFiberSpanloss(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] BatchGetFiberSpanloss failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] BatchGetFiberSpanloss results={}", resp.results_size());
    std::string json = "{\"results\": [";
    for (int i = 0; i < resp.results_size(); ++i) {
        const auto& r = resp.results(i);
        if (i > 0) json += ",";
        json += "{\"found\": " + std::string(r.found() ? "true" : "false") +
                ", \"fiber_id\": " + std::to_string(r.fiber_id());
        if (r.found()) {
            json += ", \"spanloss\": " + std::to_string(r.spanloss());
        }
        if (!r.error_message().empty())
            json += ", \"error_message\": \"" + r.error_message() + "\"";
        json += "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_colored_fibers(const std::string& color) {
    Logger::instance().info("[gRPC] GetColoredFibers color={}", color.c_str());
    fiber::maint::GetColoredFibersRequest req;
    if (color == "RED") req.set_color(fiber::common::RED);
    else if (color == "YELLOW") req.set_color(fiber::common::YELLOW);
    else if (color == "GREEN") req.set_color(fiber::common::GREEN);
    else req.set_color(fiber::common::RED);
    grpc::ClientContext ctx;
    fiber::maint::GetColoredFibersResponse resp;
    auto st = fiber_maint_stub_->GetColoredFibers(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetColoredFibers failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetColoredFibers count={}", resp.fibers_size());
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
        json += "{\"fiber\": {\"fiber_id\": " + std::to_string(f.fiber_id()) +
                ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
                ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
                ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
                ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
                ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
                ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}" +
                ", \"color\": \"" + color_str + "\"" +
                ", \"scenario_type\": " + std::to_string(cf.scene_type()) + "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_all_colored_fibers() {
    Logger::instance().info("[gRPC] GetAllColoredFibers request");
    fiber::maint::GetAllColoredFibersRequest req;
    grpc::ClientContext ctx;
    fiber::maint::GetAllColoredFibersResponse resp;
    auto st = fiber_maint_stub_->GetAllColoredFibers(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetAllColoredFibers failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetAllColoredFibers count={}", resp.fibers_size());
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
        json += "{\"fiber\": {\"fiber_id\": " + std::to_string(f.fiber_id()) +
                ", \"src_board_id\": " + std::to_string(f.src_board_id()) +
                ", \"src_port_id\": " + std::to_string(f.src_port_id()) +
                ", \"src_ne_id\": " + std::to_string(f.src_ne_id()) +
                ", \"dst_board_id\": " + std::to_string(f.dst_board_id()) +
                ", \"dst_port_id\": " + std::to_string(f.dst_port_id()) +
                ", \"dst_ne_id\": " + std::to_string(f.dst_ne_id()) + "}" +
                ", \"color\": \"" + color_str + "\"" +
                ", \"scenario_type\": " + std::to_string(cf.scene_type()) + "}";
    }
    json += "]}";
    return json;
}

std::string HttpServer::get_realtime_stats() {
    Logger::instance().trace("[gRPC] GetFiberStatsRealtime request");
    fiber::maint::GetFiberStatsRealtimeRequest req;
    grpc::ClientContext ctx;
    fiber::maint::GetFiberStatsRealtimeResponse resp;
    auto st = fiber_maint_stub_->GetFiberStatsRealtime(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiberStatsRealtime failed: {}", st.error_message()); return ""; }
    Logger::instance().trace("[gRPC] GetFiberStatsRealtime total={} red={} yellow={} green={}", resp.total_fibers(), resp.red_count(), resp.yellow_count(), resp.green_count());
    return "{\"total_fibers\": " + std::to_string(resp.total_fibers()) +
           ", \"red_count\": " + std::to_string(resp.red_count()) +
           ", \"yellow_count\": " + std::to_string(resp.yellow_count()) +
           ", \"green_count\": " + std::to_string(resp.green_count()) +
           ", \"total_colored\": " + std::to_string(resp.red_count() + resp.yellow_count()) +
           ", \"active_alarms\": " + std::to_string(resp.active_alarms()) + "}";
}

std::string HttpServer::get_stats_trend(const std::string& start_time, const std::string& end_time) {
    Logger::instance().info("[gRPC] GetFiberStatsTrend start={} end={}", start_time.c_str(), end_time.c_str());
    fiber::maint::GetFiberStatsTrendRequest req;
    req.set_start_time(start_time);
    req.set_end_time(end_time);
    grpc::ClientContext ctx;
    fiber::maint::GetFiberStatsTrendResponse resp;
    auto st = fiber_maint_stub_->GetFiberStatsTrend(&ctx, req, &resp);
    if (!st.ok()) { Logger::instance().error("[gRPC] GetFiberStatsTrend failed: {}", st.error_message()); return ""; }
    Logger::instance().info("[gRPC] GetFiberStatsTrend points={}", resp.points_size());
    std::string json = "{\"points\": [";
    for (int i = 0; i < resp.points_size(); ++i) {
        const auto& p = resp.points(i);
        if (i > 0) json += ",";
        json += "{\"timestamp\": \"" + p.timestamp() + "\"" +
                ", \"red_count\": " + std::to_string(p.red_count()) +
                ", \"yellow_count\": " + std::to_string(p.yellow_count()) +
                ", \"total_colored\": " + std::to_string(p.total_colored()) + "}";
    }
    json += "]}";
    return json;
}

// 把 MHD 内部的 "Failed to bind: ..." 接出来（buf 作为参数传入，不会被 fmt 二次解析花括号）
static void mhd_log_cb(void* /*cls*/, const char* fmt, va_list ap) {
    char buf[512];
    std::vsnprintf(buf, sizeof(buf), fmt, ap);
    Logger::instance().error("[MHD] {}", buf);
}

// MHD 把 socket 封在内部拿不到 errno，这里复刻一次 bind 抓真实错误码
// 设 SO_REUSEADDR 以对齐 MHD 自身行为，避免 TIME_WAIT 误判
static int probe_bind(uint16_t port) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return errno;
    int yes = 1;
    ::setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_ANY);
    addr.sin_port        = htons(port);
    int rc  = ::bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    int err = (rc < 0) ? errno : 0;
    ::close(fd);
    return err;
}

// ── 启动 ──
void HttpServer::start() {
    daemon_ = MHD_start_daemon(
        MHD_USE_SELECT_INTERNALLY, port_,
        nullptr, nullptr,
        &HttpServer::handle_request, this,
        MHD_OPTION_EXTERNAL_LOGGER, &mhd_log_cb, nullptr,
        MHD_OPTION_NOTIFY_COMPLETED, &HttpServer::request_completed, nullptr,
        MHD_OPTION_END);

    if (daemon_) {
        Logger::instance().info("API Gateway HTTP server listening on port: {}", port_);
        return;
    }

    // 失败：让 errno 开口
    int err = probe_bind(port_);
    Logger::instance().error(
        "Failed to start HTTP server on port {} | probe bind errno={} ({})",
        port_, err, err ? std::strerror(err) : "ok");

    switch (err) {
        case EADDRINUSE:
            Logger::instance().error(
                "  -> 端口 {} 被占用。查: sudo fuser -v {}/tcp 2>&1", port_, port_);
            break;
        case EACCES:
            Logger::instance().error("  -> 权限拒绝");
            break;
        case EADDRNOTAVAIL:
            Logger::instance().error("  -> 绑定地址不可用");
            break;
        case EMFILE:
        case ENFILE:
            Logger::instance().error("  -> fd 耗尽，ulimit -n 调大");
            break;
        case 0:
            Logger::instance().error(
                "  -> 手动 bind 成功但 MHD 失败，看上方 [MHD] 日志");
            break;
        default:
            Logger::instance().error("  -> 其它 errno: {}", err);
            break;
    }
}
