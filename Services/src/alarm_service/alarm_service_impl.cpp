#include "alarm_service_impl.h"
#include "fiber_maint.grpc.pb.h"
#include <random>
#include <sstream>
#include <iomanip>

AlarmServiceImpl::AlarmServiceImpl() : running_(true) {}

AlarmServiceImpl::~AlarmServiceImpl() {
    running_ = false;
    event_cv_.notify_all();
    
    if (cleanup_thread_.joinable()) {
        cleanup_thread_.join();
    }
}

bool AlarmServiceImpl::init() {
    Config& config = Config::instance();
    std::string host = config.get_string("db.host", "localhost");
    int port = config.get_int("db.port", 3306);
    std::string user = config.get_string("db.user", "root");
    std::string password = config.get_string("db.password", "");
    std::string database = config.get_string("db.database", "db_alarm");
    
    bool ok = DBConnectionPool::instance().init(host, port, user, password, database);
    
    if (ok) {
        cleanup_thread_ = std::thread(&AlarmServiceImpl::cleanup_task, this);
        Logger::instance().info("AlarmService initialized, cleanup task started");
    }
    
    return ok;
}

grpc::Status AlarmServiceImpl::ReportAlarm(grpc::ServerContext* context,
                                          const fiber::alarm::ReportAlarmRequest* request,
                                          fiber::alarm::ReportAlarmResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    int32_t alarm_level = request->alarm_level();
    
    char sql[512];
    sprintf(sql, "INSERT INTO current_alarms (board_id, port_id, alarm_level, raised_at) "
                 "VALUES (%d, %d, %d, NOW()) ON DUPLICATE KEY UPDATE raised_at = NOW()",
            board_id, port_id, alarm_level);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    response->set_success(true);
    response->set_message("Alarm reported");
    
    fiber::alarm::AlarmEvent event;
    event.set_event_type(fiber::common::AlarmEventType::ALARM_RAISED);
    event.set_board_id(board_id);
    event.set_port_id(port_id);
    event.set_alarm_level(static_cast<fiber::common::AlarmLevel>(alarm_level));
    event.set_timestamp(get_current_timestamp());
    push_alarm_event(event);
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::ClearAlarm(grpc::ServerContext* context,
                                         const fiber::alarm::ClearAlarmRequest* request,
                                         fiber::alarm::ClearAlarmResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    int32_t alarm_level = request->alarm_level();
    
    char sql[256];
    sprintf(sql, "SELECT raised_at FROM current_alarms WHERE board_id = %d AND port_id = %d AND alarm_level = %d",
            board_id, port_id, alarm_level);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    
    if (!row) {
        mysql_free_result(res);
        response->set_success(false);
        response->set_message("Alarm not found");
        return grpc::Status(grpc::NOT_FOUND, "Alarm not found");
    }
    
    std::string raised_at = row[0];
    mysql_free_result(res);
    
    sprintf(sql, "DELETE FROM current_alarms WHERE board_id = %d AND port_id = %d AND alarm_level = %d",
            board_id, port_id, alarm_level);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    sprintf(sql, "INSERT INTO history_alarms (board_id, port_id, alarm_level, raised_at, cleared_at) "
                 "VALUES (%d, %d, %d, '%s', NOW())", board_id, port_id, alarm_level, raised_at.c_str());
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    response->set_success(true);
    response->set_message("Alarm cleared");
    
    fiber::alarm::AlarmEvent event;
    event.set_event_type(fiber::common::AlarmEventType::ALARM_CLEARED);
    event.set_board_id(board_id);
    event.set_port_id(port_id);
    event.set_alarm_level(static_cast<fiber::common::AlarmLevel>(alarm_level));
    event.set_timestamp(get_current_timestamp());
    push_alarm_event(event);
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::GetCurrentAlarm(grpc::ServerContext* context,
                                              const fiber::alarm::GetCurrentAlarmRequest* request,
                                              fiber::alarm::GetCurrentAlarmResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    
    char sql[256];
    sprintf(sql, "SELECT board_id, port_id, alarm_level, raised_at FROM current_alarms WHERE board_id = %d AND port_id = %d",
            board_id, port_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        auto alarm = response->add_alarms();
        alarm->set_board_id(std::stoi(row[0]));
        alarm->set_port_id(std::stoi(row[1]));
        alarm->set_alarm_level(static_cast<fiber::common::AlarmLevel>(std::stoi(row[2])));
        alarm->set_raised_at(row[3]);
    }
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::BatchGetCurrentAlarms(grpc::ServerContext* context,
                                                    const fiber::alarm::BatchGetCurrentAlarmsRequest* request,
                                                    fiber::alarm::BatchGetCurrentAlarmsResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    for (const auto& port : request->ports()) {
        auto result = response->add_results();
        result->set_board_id(port.board_id());
        result->set_port_id(port.port_id());
        
        char sql[256];
        sprintf(sql, "SELECT board_id, port_id, alarm_level, raised_at FROM current_alarms WHERE board_id = %d AND port_id = %d",
                port.board_id(), port.port_id());
        
        if (mysql_query(conn.get(), sql) != 0) {
            continue;
        }
        
        MYSQL_RES* res = mysql_store_result(conn.get());
        MYSQL_ROW row;
        
        while ((row = mysql_fetch_row(res)) != nullptr) {
            auto alarm = result->add_alarms();
            alarm->set_board_id(std::stoi(row[0]));
            alarm->set_port_id(std::stoi(row[1]));
            alarm->set_alarm_level(static_cast<fiber::common::AlarmLevel>(std::stoi(row[2])));
            alarm->set_raised_at(row[3]);
        }
        
        mysql_free_result(res);
    }
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::SubscribeAlarmEvents(grpc::ServerContext* context,
                                                   const fiber::alarm::SubscribeAlarmEventsRequest* request,
                                                   grpc::ServerWriter<fiber::alarm::AlarmEvent>* writer) {
    size_t last_index = 0;
    
    while (running_) {
        try {
            std::unique_lock<std::mutex> lock(event_mutex_);
            
            while (running_ && last_index >= event_buffer_.size()) {
                event_cv_.wait(lock);
            }
            
            if (!running_) break;
            
            while (last_index < event_buffer_.size()) {
                fiber::alarm::AlarmEvent event = event_buffer_[last_index];
                last_index++;
                lock.unlock();
                
                if (!writer->Write(event)) {
                    Logger::instance().warn("Client disconnected from alarm event stream");
                    return grpc::Status::OK;
                }
                
                lock.lock();
            }
        } catch (const std::exception& e) {
            Logger::instance().error("Error in alarm event subscription: {}", e.what());
            return grpc::Status(grpc::INTERNAL, e.what());
        }
    }
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::CreatePullCall(grpc::ServerContext* context,
                                             const fiber::alarm::CreatePullCallRequest* request,
                                             fiber::alarm::CreatePullCallResponse* response) {
    std::string task_id = generate_task_id();
    
    std::lock_guard<std::mutex> lock(task_mutex_);
    
    PullCallTask task;
    task.task_id = task_id;
    task.include_history = request->include_history();
    task.callback_service_addr = request->callback_service_addr();
    
    for (const auto& port : request->ports()) {
        task.ports.push_back(port);
    }
    
    int expire_sec = request->expire_seconds();
    if (expire_sec <= 0) {
        expire_sec = 60;
    }
    
    task.expire_time = std::chrono::steady_clock::now() + std::chrono::seconds(expire_sec);
    task.status = "processing";
    pull_call_tasks_[task_id] = task;
    
    response->set_task_id(task_id);
    response->set_status("processing");
    
    std::thread(&AlarmServiceImpl::process_pull_call_task, this, task_id).detach();
    
    return grpc::Status::OK;
}

void AlarmServiceImpl::process_pull_call_task(const std::string& task_id) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        std::lock_guard<std::mutex> lock(task_mutex_);
        auto it = pull_call_tasks_.find(task_id);
        if (it != pull_call_tasks_.end()) {
            it->second.status = "failed";
        }
        return;
    }
    
    char sql[512];
    std::vector<fiber::alarm::AlarmRecord> data;
    
    {
        std::lock_guard<std::mutex> lock(task_mutex_);
        auto it = pull_call_tasks_.find(task_id);
        if (it == pull_call_tasks_.end()) {
            return;
        }
        
        const auto& task = it->second;
        
        if (task.ports.empty()) {
            sprintf(sql, "SELECT board_id, port_id, alarm_level, raised_at FROM current_alarms");
        } else {
            std::string board_ids;
            std::string port_ids;
            
            for (size_t i = 0; i < task.ports.size(); ++i) {
                if (i > 0) {
                    board_ids += ",";
                    port_ids += ",";
                }
                board_ids += std::to_string(task.ports[i].board_id());
                port_ids += std::to_string(task.ports[i].port_id());
            }
            
            sprintf(sql, "SELECT board_id, port_id, alarm_level, raised_at FROM current_alarms "
                         "WHERE board_id IN (%s) AND port_id IN (%s)", board_ids.c_str(), port_ids.c_str());
        }
    }
    
    if (mysql_query(conn.get(), sql) != 0) {
        std::lock_guard<std::mutex> lock(task_mutex_);
        auto it = pull_call_tasks_.find(task_id);
        if (it != pull_call_tasks_.end()) {
            it->second.status = "failed";
        }
        return;
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        auto alarm = fiber::alarm::AlarmRecord();
        alarm.set_board_id(std::stoi(row[0]));
        alarm.set_port_id(std::stoi(row[1]));
        alarm.set_alarm_level(static_cast<fiber::common::AlarmLevel>(std::stoi(row[2])));
        alarm.set_raised_at(row[3]);
        data.push_back(alarm);
    }
    
    mysql_free_result(res);
    
    {
        std::lock_guard<std::mutex> lock(task_mutex_);
        auto it = pull_call_tasks_.find(task_id);
        if (it != pull_call_tasks_.end()) {
            it->second.data = data;
            it->second.status = "completed";
            
            if (!it->second.callback_service_addr.empty()) {
                std::string callback_addr = it->second.callback_service_addr;
                std::vector<fiber::alarm::AlarmRecord> callback_data = data;
                std::string callback_task_id = task_id;
                
                std::thread([callback_addr, callback_data, callback_task_id]() {
                    const int max_retries = 3;
                    int retry_delay_ms = 500;
                    
                    for (int retry = 0; retry < max_retries; ++retry) {
                        try {
                            auto stub = fiber::maint::FiberMaintService::NewStub(
                                grpc::CreateChannel(callback_addr, grpc::InsecureChannelCredentials()));
                            
                            fiber::maint::PullCallResultCallbackRequest req;
                            req.set_task_id(callback_task_id);
                            req.set_status("completed");
                            for (const auto& alarm : callback_data) {
                                *req.add_alarms() = alarm;
                            }
                            
                            fiber::maint::PullCallResultCallbackResponse resp;
                            grpc::ClientContext ctx;
                            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(10));
                            
                            auto status = stub->PullCallResultCallback(&ctx, req, &resp);
                            if (status.ok()) {
                                Logger::instance().info("PullCall callback success for task {}", callback_task_id);
                                return;
                            }
                            
                            Logger::instance().warn("PullCall callback attempt {} failed for task {}: {}", 
                                                    retry + 1, callback_task_id, status.error_message());
                            
                        } catch (const std::exception& e) {
                            Logger::instance().warn("PullCall callback attempt {} exception for task {}: {}", 
                                                    retry + 1, callback_task_id, e.what());
                        }
                        
                        if (retry < max_retries - 1) {
                            std::this_thread::sleep_for(std::chrono::milliseconds(retry_delay_ms));
                            retry_delay_ms *= 2;
                        }
                    }
                    
                    Logger::instance().error("PullCall callback failed after {} retries for task {}", 
                                            max_retries, callback_task_id);
                }).detach();
            }
        }
    }
}

grpc::Status AlarmServiceImpl::GetPullCallResult(grpc::ServerContext* context,
                                                const fiber::alarm::GetPullCallResultRequest* request,
                                                fiber::alarm::GetPullCallResultResponse* response) {
    std::lock_guard<std::mutex> lock(task_mutex_);
    
    auto it = pull_call_tasks_.find(request->task_id());
    if (it == pull_call_tasks_.end()) {
        response->set_status("failed");
        return grpc::Status(grpc::NOT_FOUND, "Task not found");
    }
    
    auto& task = it->second;
    
    if (std::chrono::steady_clock::now() > task.expire_time) {
        response->set_status("failed");
        pull_call_tasks_.erase(it);
        return grpc::Status(grpc::DEADLINE_EXCEEDED, "Task expired");
    }
    
    response->set_status(task.status);
    
    for (const auto& alarm : task.data) {
        *response->add_data() = alarm;
    }
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::CancelPullCall(grpc::ServerContext* context,
                                             const fiber::alarm::CancelPullCallRequest* request,
                                             fiber::alarm::CancelPullCallResponse* response) {
    std::lock_guard<std::mutex> lock(task_mutex_);
    
    auto it = pull_call_tasks_.find(request->task_id());
    if (it == pull_call_tasks_.end()) {
        response->set_success(false);
        return grpc::Status(grpc::NOT_FOUND, "Task not found");
    }
    
    pull_call_tasks_.erase(it);
    response->set_success(true);
    
    return grpc::Status::OK;
}

grpc::Status AlarmServiceImpl::HealthCheck(grpc::ServerContext* context,
                                          const fiber::alarm::HealthCheckRequest* request,
                                          fiber::common::HealthCheckResponse* response) {
    response->set_serving(true);
    response->set_version("1.0.0");
    return grpc::Status::OK;
}

void AlarmServiceImpl::push_alarm_event(const fiber::alarm::AlarmEvent& event) {
    std::lock_guard<std::mutex> lock(event_mutex_);
    event_buffer_.push_back(event);
    if (event_buffer_.size() > 1000) {
        event_buffer_.erase(event_buffer_.begin(), event_buffer_.begin() + 500);
    }
    event_cv_.notify_all();
}

void AlarmServiceImpl::cleanup_task() {
    while (running_) {
        try {
            std::lock_guard<std::mutex> lock(task_mutex_);
            auto now = std::chrono::steady_clock::now();
            
            for (auto it = pull_call_tasks_.begin(); it != pull_call_tasks_.end();) {
                if (now > it->second.expire_time) {
                    it = pull_call_tasks_.erase(it);
                } else {
                    ++it;
                }
            }
        } catch (const std::exception& e) {
            Logger::instance().error("Cleanup task exception: {}", e.what());
        }
        
        std::this_thread::sleep_for(std::chrono::seconds(30));
    }
}

std::string AlarmServiceImpl::generate_task_id() {
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> dis(0, 9);
    
    std::stringstream ss;
    ss << std::hex << std::setw(16) << std::setfill('0') << std::chrono::system_clock::now().time_since_epoch().count();
    
    for (int i = 0; i < 8; ++i) {
        ss << dis(gen);
    }
    
    return ss.str();
}