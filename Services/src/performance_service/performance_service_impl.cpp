#include "performance_service_impl.h"

PerformanceServiceImpl::PerformanceServiceImpl() : running_(true) {}

PerformanceServiceImpl::~PerformanceServiceImpl() {
    running_ = false;
    if (archive_thread_.joinable()) {
        archive_thread_.join();
    }
}

bool PerformanceServiceImpl::init() {
    Config& config = Config::instance();
    std::string host = config.get_string("db.host", "localhost");
    int port = config.get_int("db.port", 3306);
    std::string user = config.get_string("db.user", "root");
    std::string password = config.get_string("db.password", "");
    std::string database = config.get_string("db.database", "db_performance");
    
    bool ok = DBConnectionPool::instance().init(host, port, user, password, database);
    
    if (ok) {
        archive_thread_ = std::thread(&PerformanceServiceImpl::archive_task, this);
        Logger::instance().info("PerformanceService initialized, archive task started");
    }
    
    return ok;
}

grpc::Status PerformanceServiceImpl::ReportPerformance(grpc::ServerContext* context,
                                                      const fiber::performance::ReportPerformanceRequest* request,
                                                      fiber::performance::ReportPerformanceResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    double oop_value = request->oop_value();
    double iop_value = request->iop_value();
    
    char sql[512];
    sprintf(sql, "INSERT INTO current_performance (board_id, port_id, oop_value, iop_value) "
                 "VALUES (%d, %d, %f, %f) ON DUPLICATE KEY UPDATE "
                 "oop_value = VALUES(oop_value), iop_value = VALUES(iop_value), updated_at = CURRENT_TIMESTAMP",
            board_id, port_id, oop_value, iop_value);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        Logger::instance().error("ReportPerformance INSERT failed: {}", mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    response->set_success(true);
    response->set_message("Performance reported");
    
    return grpc::Status::OK;
}

grpc::Status PerformanceServiceImpl::GetCurrentPerformance(grpc::ServerContext* context,
                                                          const fiber::performance::GetCurrentPerformanceRequest* request,
                                                          fiber::performance::GetCurrentPerformanceResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    
    char sql[256];
    sprintf(sql, "SELECT oop_value, iop_value, updated_at FROM current_performance WHERE board_id = %d AND port_id = %d",
            board_id, port_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    
    if (!row) {
        mysql_free_result(res);
        return grpc::Status(grpc::NOT_FOUND, "No performance data found");
    }
    
    response->set_board_id(board_id);
    response->set_port_id(port_id);
    response->set_oop_value(row[0] ? std::stod(row[0]) : 0.0);
    response->set_iop_value(row[1] ? std::stod(row[1]) : 0.0);
    response->set_updated_at(row[2]);
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status PerformanceServiceImpl::GetHistoryPerformance(grpc::ServerContext* context,
                                                          const fiber::performance::GetHistoryPerformanceRequest* request,
                                                          fiber::performance::GetHistoryPerformanceResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    std::string start_time = request->start_time();
    std::string end_time = request->end_time();
    
    char sql[512];
    sprintf(sql, "SELECT recorded_at, oop_value, iop_value FROM history_performance "
                 "WHERE board_id = %d AND port_id = %d AND recorded_at BETWEEN '%s' AND '%s' ORDER BY recorded_at",
            board_id, port_id, start_time.c_str(), end_time.c_str());
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        auto record = response->add_records();
        record->set_recorded_at(row[0]);
        record->set_oop_value(row[1] ? std::stod(row[1]) : 0.0);
        record->set_iop_value(row[2] ? std::stod(row[2]) : 0.0);
    }
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status PerformanceServiceImpl::BatchGetCurrentPerformance(grpc::ServerContext* context,
                                                               const fiber::performance::BatchGetCurrentPerformanceRequest* request,
                                                               fiber::performance::BatchGetCurrentPerformanceResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    for (const auto& port : request->ports()) {
        auto result = response->add_results();
        result->set_found(false);
        result->set_board_id(port.board_id());
        result->set_port_id(port.port_id());
        
        char sql[256];
        sprintf(sql, "SELECT oop_value, iop_value FROM current_performance WHERE board_id = %d AND port_id = %d",
                port.board_id(), port.port_id());
        
        if (mysql_query(conn.get(), sql) != 0) {
            result->set_error_message(mysql_error(conn.get()));
            continue;
        }
        
        MYSQL_RES* res = mysql_store_result(conn.get());
        MYSQL_ROW row = mysql_fetch_row(res);
        
        if (!row) {
            mysql_free_result(res);
            result->set_error_message("No data found");
            continue;
        }
        
        result->set_found(true);
        result->set_oop_value(row[0] ? std::stod(row[0]) : 0.0);
        result->set_iop_value(row[1] ? std::stod(row[1]) : 0.0);
        
        mysql_free_result(res);
    }
    
    return grpc::Status::OK;
}

grpc::Status PerformanceServiceImpl::BatchGetHistoryPerformance(grpc::ServerContext* context,
                                                               const fiber::performance::BatchGetHistoryPerformanceRequest* request,
                                                               fiber::performance::BatchGetHistoryPerformanceResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    std::string start_time = request->start_time();
    std::string end_time = request->end_time();
    
    for (const auto& port : request->ports()) {
        auto result = response->add_results();
        result->set_board_id(port.board_id());
        result->set_port_id(port.port_id());
        
        char sql[512];
        sprintf(sql, "SELECT recorded_at, oop_value, iop_value FROM history_performance "
                     "WHERE board_id = %d AND port_id = %d AND recorded_at BETWEEN '%s' AND '%s' ORDER BY recorded_at",
                port.board_id(), port.port_id(), start_time.c_str(), end_time.c_str());
        
        if (mysql_query(conn.get(), sql) != 0) {
            continue;
        }
        
        MYSQL_RES* res = mysql_store_result(conn.get());
        MYSQL_ROW row;
        
        while ((row = mysql_fetch_row(res)) != nullptr) {
            auto record = result->add_records();
            record->set_recorded_at(row[0]);
            record->set_oop_value(row[1] ? std::stod(row[1]) : 0.0);
            record->set_iop_value(row[2] ? std::stod(row[2]) : 0.0);
        }
        
        mysql_free_result(res);
    }
    
    return grpc::Status::OK;
}

grpc::Status PerformanceServiceImpl::HealthCheck(grpc::ServerContext* context,
                                                 const fiber::performance::HealthCheckRequest* request,
                                                 fiber::common::HealthCheckResponse* response) {
    response->set_serving(true);
    response->set_version("1.0.0");
    return grpc::Status::OK;
}

void PerformanceServiceImpl::archive_task() {
    int interval_min = Config::instance().get_int("perf.archive_interval_min", 15);
    
    while (running_) {
        try {
            auto conn = DBConnectionPool::instance().get_connection();
            if (!conn) {
                std::this_thread::sleep_for(std::chrono::minutes(interval_min));
                continue;
            }
            
            char sql[512];
            sprintf(sql, "INSERT INTO history_performance (board_id, port_id, recorded_at, oop_value, iop_value) "
                         "SELECT board_id, port_id, NOW(), oop_value, iop_value FROM current_performance");
            
            if (mysql_query(conn.get(), sql) != 0) {
                Logger::instance().error("Archive INSERT failed: {}", mysql_error(conn.get()));
            } else {
                sprintf(sql, "DELETE FROM current_performance");
                if (mysql_query(conn.get(), sql) != 0) {
                    Logger::instance().error("Archive DELETE failed: {}", mysql_error(conn.get()));
                } else {
                    Logger::instance().info("Performance archive completed");
                }
            }
        } catch (const std::exception& e) {
            Logger::instance().error("Archive task exception: {}", e.what());
        }
        
        std::this_thread::sleep_for(std::chrono::minutes(interval_min));
    }
}