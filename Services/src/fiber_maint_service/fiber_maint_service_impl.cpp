#include "fiber_maint_service_impl.h"

FiberMaintServiceImpl::FiberMaintServiceImpl() : running_(true) {}

FiberMaintServiceImpl::~FiberMaintServiceImpl() {
    running_ = false;
    task_cv_.notify_all();
    
    if (alarm_sub_thread_.joinable()) alarm_sub_thread_.join();
    if (fiber_sub_thread_.joinable()) fiber_sub_thread_.join();
    if (trend_thread_.joinable()) trend_thread_.join();
    
    for (auto& t : worker_threads_) {
        if (t.joinable()) t.join();
    }
}

bool FiberMaintServiceImpl::init() {
    Config& config = Config::instance();
    std::string host = config.get_string("db.host", "localhost");
    int port = config.get_int("db.port", 3306);
    std::string user = config.get_string("db.user", "root");
    std::string password = config.get_string("db.password", "");
    std::string database = config.get_string("db.database", "db_fiber_maint");
    
    bool ok = DBConnectionPool::instance().init(host, port, user, password, database);
    
    if (!ok) {
        return false;
    }
    
    std::string alarm_addr = config.get_string("alarm_service.addr", "localhost:50054");
    std::string topology_addr = config.get_string("topology_service.addr", "localhost:50052");
    std::string perf_addr = config.get_string("performance_service.addr", "localhost:50053");
    
    alarm_stub_ = fiber::alarm::AlarmService::NewStub(grpc::CreateChannel(alarm_addr, grpc::InsecureChannelCredentials()));
    topology_stub_ = fiber::topology::TopologyService::NewStub(grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials()));
    perf_stub_ = fiber::performance::PerformanceService::NewStub(grpc::CreateChannel(perf_addr, grpc::InsecureChannelCredentials()));
    
    sync_fiber_cache();
    sync_color_cache();
    
    int worker_count = std::thread::hardware_concurrency();
    if (worker_count == 0) worker_count = 4;
    
    for (int i = 0; i < worker_count; ++i) {
        worker_threads_.emplace_back(&FiberMaintServiceImpl::color_recalc_worker, this);
    }
    
    alarm_sub_thread_ = std::thread(&FiberMaintServiceImpl::subscribe_alarm_events, this);
    fiber_sub_thread_ = std::thread(&FiberMaintServiceImpl::subscribe_fiber_events, this);
    trend_thread_ = std::thread(&FiberMaintServiceImpl::trend_task, this);
    
    std::thread(&FiberMaintServiceImpl::init_alarm_sync_async, this).detach();
    
    Logger::instance().info("FiberMaintService initialized");
    return true;
}

std::string FiberMaintServiceImpl::get_callback_addr() {
    Config& config = Config::instance();
    std::string callback_addr = config.get_string("callback_service_addr", "");
    if (!callback_addr.empty()) {
        return callback_addr;
    }
    return config.get_string("server.addr", "localhost:50051");
}

void FiberMaintServiceImpl::init_alarm_sync_async() {
    fiber::alarm::CreatePullCallRequest req;
    req.set_include_history(false);
    
    std::string callback_addr = get_callback_addr();
    req.set_callback_service_addr(callback_addr);
    
    grpc::ClientContext ctx1;
    fiber::alarm::CreatePullCallResponse resp;
    
    auto status = alarm_stub_->CreatePullCall(&ctx1, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("CreatePullCall failed: {}", status.error_message());
        return;
    }
    
    Logger::instance().info("PullCall created, task_id: {}, callback_addr: {}", resp.task_id(), callback_addr);
}

void FiberMaintServiceImpl::sync_alarm_cache() {
    fiber::alarm::CreatePullCallRequest req;
    req.set_include_history(false);
    
    std::string callback_addr = get_callback_addr();
    req.set_callback_service_addr(callback_addr);
    
    grpc::ClientContext ctx1;
    fiber::alarm::CreatePullCallResponse resp;
    
    auto status = alarm_stub_->CreatePullCall(&ctx1, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("CreatePullCall failed: {}", status.error_message());
        return;
    }
    
    Logger::instance().info("sync_alarm_cache PullCall created, task_id: {}", resp.task_id());
}

void FiberMaintServiceImpl::sync_fiber_cache() {
    fiber::topology::BatchGetFibersRequest req;
    
    grpc::ClientContext ctx;
    fiber::topology::BatchGetFibersResponse resp;
    
    auto status = topology_stub_->BatchGetFibers(&ctx, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("BatchGetFibers failed: {}", status.error_message());
        return;
    }
    
    std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
    fiber_by_id_.clear();
    fiber_by_port_.clear();
    
    for (const auto& result : resp.results()) {
        if (!result.found()) continue;
        
        const auto& fiber = result.fiber();
        
        FiberCacheEntry entry;
        entry.fiber_id = fiber.fiber_id();
        entry.src_board_id = fiber.src_board_id();
        entry.src_port_id = fiber.src_port_id();
        entry.src_ne_id = fiber.src_ne_id();
        entry.dst_board_id = fiber.dst_board_id();
        entry.dst_port_id = fiber.dst_port_id();
        entry.dst_ne_id = fiber.dst_ne_id();
        entry.is_inter_ne = (fiber.src_ne_id() != fiber.dst_ne_id());
        
        fiber_by_id_[entry.fiber_id] = entry;
        fiber_by_port_.insert({{entry.src_board_id, entry.src_port_id}, entry.fiber_id});
        fiber_by_port_.insert({{entry.dst_board_id, entry.dst_port_id}, entry.fiber_id});
    }
    
    Logger::instance().info("Fiber cache synced, {} entries", fiber_by_id_.size());
}

void FiberMaintServiceImpl::sync_color_cache() {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        Logger::instance().error("sync_color_cache failed: DB connection failed");
        return;
    }
    
    char sql[256];
    sprintf(sql, "SELECT fiber_id, color, scene_type FROM fiber_colors WHERE color IN (2, 3)");
    
    if (mysql_query(conn.get(), sql) != 0) {
        Logger::instance().error("sync_color_cache failed: {}", mysql_error(conn.get()));
        return;
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    
    std::lock_guard<std::mutex> lock(color_cache_mutex_);
    color_by_fiber_.clear();
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        int8_t color = static_cast<int8_t>(std::stoi(row[1]));
        if (color == fiber::common::FiberColor::RED || color == fiber::common::FiberColor::YELLOW) {
            FiberColorCacheEntry entry;
            entry.color = color;
            if (row[2]) {
                entry.scene_type = std::stoi(row[2]);
            }
            color_by_fiber_[std::stoi(row[0])] = entry;
        }
    }
    
    mysql_free_result(res);
    
    Logger::instance().info("Color cache synced, {} entries", color_by_fiber_.size());
}

void FiberMaintServiceImpl::full_color_recalc() {
    std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
    
    for (const auto& pair : fiber_by_id_) {
        const auto& entry = pair.second;
        if (!entry.is_inter_ne) continue;
        
        int32_t scene_type = 1;
        int32_t scenario_case = 0;
        int8_t color = calculate_color(entry.fiber_id, scene_type, scenario_case);
        
        auto conn = DBConnectionPool::instance().get_connection();
        if (!conn) continue;
        
        char sql[512];
        sprintf(sql, "INSERT INTO fiber_colors (fiber_id, color, scene_type, scenario_case) "
                     "VALUES (%d, %d, %d, %d) ON DUPLICATE KEY UPDATE "
                     "color = VALUES(color), scene_type = VALUES(scene_type), scenario_case = VALUES(scenario_case)",
                entry.fiber_id, color, scene_type, scenario_case);
        
        mysql_query(conn.get(), sql);
    }
    
    Logger::instance().info("Full color recalculation completed");
}

void FiberMaintServiceImpl::subscribe_alarm_events() {
    while (running_) {
        try {
            fiber::alarm::SubscribeAlarmEventsRequest req;
            grpc::ClientContext ctx;
            
            std::unique_ptr<grpc::ClientReader<fiber::alarm::AlarmEvent>> reader(alarm_stub_->SubscribeAlarmEvents(&ctx, req));
            
            fiber::alarm::AlarmEvent event;
            while (running_ && reader->Read(&event)) {
                process_alarm_event(event);
            }
            
            Logger::instance().warn("Alarm event subscription disconnected, reconnecting...");
        } catch (const std::exception& e) {
            Logger::instance().error("Alarm event subscription error: {}, reconnecting...", e.what());
        }
        
        if (running_) {
            std::this_thread::sleep_for(std::chrono::seconds(5));
        }
    }
}

void FiberMaintServiceImpl::subscribe_fiber_events() {
    fiber::topology::SubscribeFiberEventsRequest req;
    grpc::ClientContext ctx;
    
    std::unique_ptr<grpc::ClientReader<fiber::topology::FiberEvent>> reader(topology_stub_->SubscribeFiberEvents(&ctx, req));
    
    fiber::topology::FiberEvent event;
    while (running_ && reader->Read(&event)) {
        process_fiber_event(event);
    }
    
    Logger::instance().warn("Fiber event subscription disconnected");
}

void FiberMaintServiceImpl::process_alarm_event(const fiber::alarm::AlarmEvent& event) {
    {
        std::lock_guard<std::mutex> lock(alarm_cache_mutex_);
        
        AlarmCacheKey key = {event.board_id(), event.port_id(), event.alarm_level()};
        
        if (event.event_type() == fiber::common::AlarmEventType::ALARM_RAISED) {
            AlarmCacheValue value = {event.timestamp()};
            alarm_cache_[key] = value;
        } else {
            alarm_cache_.erase(key);
        }
    }
    
    std::vector<int32_t> affected_fibers = find_affected_fibers(event.board_id(), event.port_id());
    
    for (int32_t fiber_id : affected_fibers) {
        enqueue_color_recalc(fiber_id, [this, fiber_id]() {
            recalculate_fiber_color(fiber_id);
        });
    }
}

void FiberMaintServiceImpl::process_fiber_event(const fiber::topology::FiberEvent& event) {
    if (event.event_type() == fiber::common::FiberEventType::FIBER_CREATED) {
        fiber::topology::GetFiberRequest req;
        req.set_fiber_id(event.fiber_id());
        fiber::topology::GetFiberResponse resp;
        
        grpc::ClientContext ctx;
        auto status = topology_stub_->GetFiber(&ctx, req, &resp);
        
        if (status.ok()) {
            const auto& fiber = resp.fiber();
            
            FiberCacheEntry entry;
            entry.fiber_id = fiber.fiber_id();
            entry.src_board_id = fiber.src_board_id();
            entry.src_port_id = fiber.src_port_id();
            entry.src_ne_id = fiber.src_ne_id();
            entry.dst_board_id = fiber.dst_board_id();
            entry.dst_port_id = fiber.dst_port_id();
            entry.dst_ne_id = fiber.dst_ne_id();
            entry.is_inter_ne = (fiber.src_ne_id() != fiber.dst_ne_id());
            
            {
                std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
                fiber_by_id_[entry.fiber_id] = entry;
                fiber_by_port_.insert({{entry.src_board_id, entry.src_port_id}, entry.fiber_id});
                fiber_by_port_.insert({{entry.dst_board_id, entry.dst_port_id}, entry.fiber_id});
            }
            
            if (entry.is_inter_ne) {
                enqueue_color_recalc(entry.fiber_id, [this, entry]() {
                    init_fiber_color(entry);
                });
            }
        }
    } else {
        FiberCacheEntry entry;
        bool found = false;
        
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(event.fiber_id());
            if (it != fiber_by_id_.end()) {
                entry = it->second;
                found = true;
                fiber_by_id_.erase(it);
            }
        }
        
        if (found) {
            {
                std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
                auto range = fiber_by_port_.equal_range({entry.src_board_id, entry.src_port_id});
                for (auto it = range.first; it != range.second; ++it) {
                    if (it->second == entry.fiber_id) {
                        fiber_by_port_.erase(it);
                        break;
                    }
                }
                
                range = fiber_by_port_.equal_range({entry.dst_board_id, entry.dst_port_id});
                for (auto it = range.first; it != range.second; ++it) {
                    if (it->second == entry.fiber_id) {
                        fiber_by_port_.erase(it);
                        break;
                    }
                }
            }
            
            if (entry.is_inter_ne) {
                auto conn = DBConnectionPool::instance().get_connection();
                if (conn) {
                    char sql[256];
                    sprintf(sql, "DELETE FROM fiber_colors WHERE fiber_id = %d", entry.fiber_id);
                    mysql_query(conn.get(), sql);
                }
                
                {
                    std::lock_guard<std::mutex> lock(color_cache_mutex_);
                    color_by_fiber_.erase(entry.fiber_id);
                }
            } else {
                std::vector<int32_t> affected_fibers;
                
                {
                    std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
                    
                    int32_t passive_board = 0;
                    int8_t passive_port = 0;
                    
                    if ((entry.src_port_id == 2 || entry.src_port_id == 3)) {
                        passive_board = entry.src_board_id;
                        passive_port = entry.src_port_id;
                    } else if ((entry.dst_port_id == 2 || entry.dst_port_id == 3)) {
                        passive_board = entry.dst_board_id;
                        passive_port = entry.dst_port_id;
                    }
                    
                    if (passive_board != 0 && (passive_port == 2 || passive_port == 3)) {
                        auto inter_range = fiber_by_port_.equal_range({passive_board, 1});
                        for (auto it = inter_range.first; it != inter_range.second; ++it) {
                            int32_t inter_fiber_id = it->second;
                            auto inter_it = fiber_by_id_.find(inter_fiber_id);
                            if (inter_it != fiber_by_id_.end() && inter_it->second.is_inter_ne) {
                                affected_fibers.push_back(inter_fiber_id);
                            }
                        }
                    }
                }
                
                for (int32_t fiber_id : affected_fibers) {
                    enqueue_color_recalc(fiber_id, [this, fiber_id]() {
                        recalculate_fiber_color(fiber_id);
                    });
                }
            }
        }
    }
}

std::vector<int32_t> FiberMaintServiceImpl::find_affected_fibers(int32_t board_id, int8_t port_id) {
    std::vector<int32_t> affected;
    std::unordered_set<int32_t> visited;
    
    std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
    
    auto range = fiber_by_port_.equal_range({board_id, port_id});
    for (auto it = range.first; it != range.second; ++it) {
        int32_t fiber_id = it->second;
        
        if (visited.count(fiber_id)) continue;
        visited.insert(fiber_id);
        
        auto entry_it = fiber_by_id_.find(fiber_id);
        if (entry_it == fiber_by_id_.end()) continue;
        
        const auto& entry = entry_it->second;
        
        if (entry.is_inter_ne) {
            if (entry.dst_board_id == board_id) {
                affected.push_back(fiber_id);
            }
            continue;
        }
        
        int32_t other_board = (entry.src_board_id == board_id) ? entry.dst_board_id : entry.src_board_id;
        int8_t other_port = (entry.src_board_id == board_id) ? entry.dst_port_id : entry.src_port_id;
        
        bool is_passive_port = (other_port == 2 || other_port == 3);
        
        if (!is_passive_port) {
            continue;
        }
        
        auto inter_range = fiber_by_port_.equal_range({other_board, 1});
        for (auto inter_it = inter_range.first; inter_it != inter_range.second; ++inter_it) {
            int32_t inter_fiber_id = inter_it->second;
            if (visited.count(inter_fiber_id)) continue;
            
            auto inter_entry_it = fiber_by_id_.find(inter_fiber_id);
            if (inter_entry_it == fiber_by_id_.end()) continue;
            
            const auto& inter_entry = inter_entry_it->second;
            if (!inter_entry.is_inter_ne) continue;
            
            if (inter_entry.dst_board_id == other_board) {
                affected.push_back(inter_fiber_id);
                visited.insert(inter_fiber_id);
            }
        }
    }
    
    return affected;
}

void FiberMaintServiceImpl::enqueue_color_recalc(int32_t fiber_id, std::function<void()> task) {
    std::lock_guard<std::mutex> lock(task_mutex_);
    recalc_tasks_[fiber_id].push(task);
    task_cv_.notify_one();
}

void FiberMaintServiceImpl::color_recalc_worker() {
    while (running_) {
        std::unique_lock<std::mutex> lock(task_mutex_);
        task_cv_.wait(lock, [this]() {
            for (const auto& pair : recalc_tasks_) {
                if (!pair.second.empty()) return true;
            }
            return !running_;
        });
        
        if (!running_) break;
        
        for (auto it = recalc_tasks_.begin(); it != recalc_tasks_.end();) {
            if (!it->second.empty()) {
                int32_t fiber_id = it->first;
                
                if (running_fibers_.count(fiber_id)) {
                    ++it;
                    continue;
                }
                
                running_fibers_.insert(fiber_id);
                auto task = it->second.front();
                it->second.pop();
                
                if (it->second.empty()) {
                    it = recalc_tasks_.erase(it);
                } else {
                    ++it;
                }
                
                lock.unlock();
                
                try {
                    task();
                } catch (const std::exception& e) {
                    Logger::instance().error("Color recalc task exception: {}", e.what());
                }
                
                lock.lock();
                running_fibers_.erase(fiber_id);
            } else {
                ++it;
            }
        }
    }
}

void FiberMaintServiceImpl::recalculate_fiber_color(int32_t fiber_id) {
    FiberCacheEntry entry;
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        auto it = fiber_by_id_.find(fiber_id);
        if (it == fiber_by_id_.end()) return;
        entry = it->second;
    }
    
    if (!entry.is_inter_ne) return;
    
    int32_t scene_type = 1;
    int32_t scenario_case = 0;
    int8_t new_color = calculate_color(fiber_id, scene_type, scenario_case);
    
    update_fiber_color(fiber_id, new_color, scene_type, scenario_case);
}

void FiberMaintServiceImpl::init_fiber_color(const FiberCacheEntry& entry) {
    if (!entry.is_inter_ne) return;
    
    int32_t scene_type = 1;
    int32_t scenario_case = 0;
    int8_t color = calculate_color(entry.fiber_id, scene_type, scenario_case);
    
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return;
    
    char sql[512];
    sprintf(sql, "INSERT INTO fiber_colors (fiber_id, color, scene_type, scenario_case) "
                 "VALUES (%d, %d, %d, %d)", entry.fiber_id, color, scene_type, scenario_case);
    
    mysql_query(conn.get(), sql);
    
    {
        std::lock_guard<std::mutex> lock(color_cache_mutex_);
        if (color == fiber::common::FiberColor::RED || color == fiber::common::FiberColor::YELLOW) {
            FiberColorCacheEntry color_entry;
            color_entry.color = color;
            color_entry.scene_type = scene_type;
            color_by_fiber_[entry.fiber_id] = color_entry;
        }
    }
    
    if (color != fiber::common::FiberColor::GREEN) {
        sprintf(sql, "INSERT INTO fiber_color_changes (fiber_id, old_color, new_color) "
                     "VALUES (%d, 1, %d)", entry.fiber_id, color);
        mysql_query(conn.get(), sql);
    }
}

bool FiberMaintServiceImpl::has_alarm(int32_t board_id, int8_t port_id, int8_t alarm_level) {
    std::lock_guard<std::mutex> lock(alarm_cache_mutex_);
    AlarmCacheKey key = {board_id, port_id, alarm_level};
    return alarm_cache_.count(key) > 0;
}

PortAlarmSummary FiberMaintServiceImpl::get_port_alarm_summary(int32_t board_id, int8_t port_id) {
    return {
        .has_critical = has_alarm(board_id, port_id, fiber::common::AlarmLevel::CRITICAL),
        .has_minor = has_alarm(board_id, port_id, fiber::common::AlarmLevel::MINOR)
    };
}

int8_t FiberMaintServiceImpl::calculate_color(int32_t fiber_id, int32_t& scene_type, int32_t& scenario_case) {
    FiberCacheEntry entry;
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        auto it = fiber_by_id_.find(fiber_id);
        if (it == fiber_by_id_.end()) return fiber::common::FiberColor::GREEN;
        entry = it->second;
    }
    
    std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
    
    auto dst_range = fiber_by_port_.equal_range({entry.dst_board_id, 1});
    bool has_inter_ne_fiber = false;
    for (auto it = dst_range.first; it != dst_range.second; ++it) {
        if (it->second == fiber_id) {
            has_inter_ne_fiber = true;
            break;
        }
    }
    
    bool is_passive_dst = false;
    auto port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
    for (auto it = port2_range.first; it != port2_range.second; ++it) {
        int32_t f_id = it->second;
        auto f_it = fiber_by_id_.find(f_id);
        if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
            is_passive_dst = true;
            break;
        }
    }
    
    if (!is_passive_dst) {
        scene_type = 1;
        scenario_case = 0;
        
        auto alarm = get_port_alarm_summary(entry.dst_board_id, 1);
        if (alarm.has_critical) {
            return fiber::common::FiberColor::RED;
        } else if (alarm.has_minor) {
            return fiber::common::FiberColor::YELLOW;
        } else {
            return fiber::common::FiberColor::GREEN;
        }
    }
    
    scene_type = 2;
    
    bool has_port2_fiber = false;
    bool has_port3_fiber = false;
    int32_t board_B = 0;
    int32_t board_A2 = 0;
    
    port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
    for (auto it = port2_range.first; it != port2_range.second; ++it) {
        int32_t f_id = it->second;
        auto f_it = fiber_by_id_.find(f_id);
        if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
            has_port2_fiber = true;
            board_B = (f_it->second.src_board_id == entry.dst_board_id) 
                ? f_it->second.dst_board_id : f_it->second.src_board_id;
            break;
        }
    }
    
    auto port3_range = fiber_by_port_.equal_range({entry.dst_board_id, 3});
    for (auto it = port3_range.first; it != port3_range.second; ++it) {
        int32_t f_id = it->second;
        auto f_it = fiber_by_id_.find(f_id);
        if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
            has_port3_fiber = true;
            board_A2 = (f_it->second.src_board_id == entry.dst_board_id) 
                ? f_it->second.dst_board_id : f_it->second.src_board_id;
            break;
        }
    }
    
    if (!has_port2_fiber) {
        scenario_case = 3;
        return fiber::common::FiberColor::GREEN;
    }
    
    if (has_port3_fiber) {
        scenario_case = 1;
        
        auto alarm_B = get_port_alarm_summary(board_B, 1);
        auto alarm_A2 = get_port_alarm_summary(board_A2, 1);
        
        if (alarm_B.has_critical && alarm_A2.has_critical) {
            return fiber::common::FiberColor::RED;
        } else if (alarm_B.has_minor || alarm_A2.has_minor ||
                   (alarm_B.has_critical && alarm_A2.has_minor) ||
                   (alarm_A2.has_critical && alarm_B.has_minor)) {
            return fiber::common::FiberColor::YELLOW;
        } else if (alarm_B.has_critical && !alarm_A2.has_critical && !alarm_A2.has_minor) {
            return fiber::common::FiberColor::GREEN;
        } else if (alarm_A2.has_critical && !alarm_B.has_critical && !alarm_B.has_minor) {
            return fiber::common::FiberColor::GREEN;
        } else {
            return fiber::common::FiberColor::GREEN;
        }
    } else {
        scenario_case = 2;
        
        auto alarm_B = get_port_alarm_summary(board_B, 1);
        
        if (alarm_B.has_critical) {
            return fiber::common::FiberColor::RED;
        } else if (alarm_B.has_minor) {
            return fiber::common::FiberColor::YELLOW;
        } else {
            return fiber::common::FiberColor::GREEN;
        }
    }
}

void FiberMaintServiceImpl::update_fiber_color(int32_t fiber_id, int8_t new_color, int32_t scene_type, int32_t scenario_case) {
    int8_t old_color = fiber::common::FiberColor::GREEN;
    bool cached = false;
    
    {
        std::lock_guard<std::mutex> lock(color_cache_mutex_);
        auto it = color_by_fiber_.find(fiber_id);
        if (it != color_by_fiber_.end()) {
            old_color = it->second.color;
            cached = true;
        }
    }
    
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return;
    
    char sql[256];
    sprintf(sql, "UPDATE fiber_colors SET color = %d, scene_type = %d, scenario_case = %d WHERE fiber_id = %d",
            new_color, scene_type, scenario_case, fiber_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        sprintf(sql, "INSERT INTO fiber_colors (fiber_id, color, scene_type, scenario_case) VALUES (%d, %d, %d, %d)",
                fiber_id, new_color, scene_type, scenario_case);
        mysql_query(conn.get(), sql);
        old_color = fiber::common::FiberColor::GREEN;
    }
    
    {
        std::lock_guard<std::mutex> lock(color_cache_mutex_);
        if (new_color == fiber::common::FiberColor::RED || new_color == fiber::common::FiberColor::YELLOW) {
            FiberColorCacheEntry entry;
            entry.color = new_color;
            color_by_fiber_[fiber_id] = entry;
        } else {
            color_by_fiber_.erase(fiber_id);
        }
    }
    
    if (old_color != new_color) {
        sprintf(sql, "INSERT INTO fiber_color_changes (fiber_id, old_color, new_color) VALUES (%d, %d, %d)",
                fiber_id, old_color, new_color);
        mysql_query(conn.get(), sql);
        
        FiberCacheEntry fiber_entry;
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(fiber_id);
            if (it != fiber_by_id_.end()) {
                fiber_entry = it->second;
            }
        }
        
        fiber::maint::FiberColorEvent event;
        event.set_fiber_id(fiber_id);
        
        auto fiber_info = event.mutable_fiber();
        fiber_info->set_fiber_id(fiber_entry.fiber_id);
        fiber_info->set_src_board_id(fiber_entry.src_board_id);
        fiber_info->set_src_port_id(fiber_entry.src_port_id);
        fiber_info->set_src_ne_id(fiber_entry.src_ne_id);
        fiber_info->set_dst_board_id(fiber_entry.dst_board_id);
        fiber_info->set_dst_port_id(fiber_entry.dst_port_id);
        fiber_info->set_dst_ne_id(fiber_entry.dst_ne_id);
        
        event.set_old_color(static_cast<fiber::common::FiberColor>(old_color));
        event.set_new_color(static_cast<fiber::common::FiberColor>(new_color));
        event.set_scene_type(scene_type);
        event.set_scenario_case(scenario_case);
        event.set_timestamp(get_current_timestamp());
        
        push_color_event(event);
    }
}

void FiberMaintServiceImpl::push_color_event(const fiber::maint::FiberColorEvent& event) {
    std::lock_guard<std::mutex> lock(writer_mutex_);
    
    for (size_t i = 0; i < color_event_writers_.size();) {
        grpc::ServerWriter<fiber::maint::FiberColorEvent>* writer = color_event_writers_[i];
        
        grpc::WriteOptions options;
        if (!writer->Write(event, options)) {
            color_event_writers_.erase(color_event_writers_.begin() + i);
        } else {
            ++i;
        }
    }
    
    Logger::instance().info("Color event pushed for fiber {}: {} -> {}", 
                            event.fiber_id(), 
                            event.old_color(), 
                            event.new_color());
}

grpc::Status FiberMaintServiceImpl::SubscribeFiberColorEvents(grpc::ServerContext* context,
                                                              const fiber::maint::SubscribeFiberColorEventsRequest* request,
                                                              grpc::ServerWriter<fiber::maint::FiberColorEvent>* writer) {
    {
        std::lock_guard<std::mutex> lock(writer_mutex_);
        color_event_writers_.push_back(writer);
    }
    
    Logger::instance().info("New fiber color event subscriber");
    
    while (!context->IsCancelled() && running_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    
    {
        std::lock_guard<std::mutex> lock(writer_mutex_);
        auto it = std::find(color_event_writers_.begin(), color_event_writers_.end(), writer);
        if (it != color_event_writers_.end()) {
            color_event_writers_.erase(it);
        }
    }
    
    Logger::instance().info("Fiber color event subscriber disconnected");
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::PullCallResultCallback(grpc::ServerContext* context,
                                                           const fiber::maint::PullCallResultCallbackRequest* request,
                                                           fiber::maint::PullCallResultCallbackResponse* response) {
    Logger::instance().info("PullCallResultCallback received for task: {}", request->task_id());
    
    {
        std::lock_guard<std::mutex> lock(alarm_cache_mutex_);
        for (const auto& alarm : request->alarms()) {
            AlarmCacheKey key;
            key.board_id = alarm.board_id();
            key.port_id = alarm.port_id();
            key.alarm_level = alarm.alarm_level();
            
            AlarmCacheValue value;
            value.raised_at = alarm.raised_at();
            
            alarm_cache_[key] = value;
        }
    }
    
    full_color_recalc();
    
    response->set_success(true);
    response->set_message("Alarm cache synced and color recalculation triggered");
    
    return grpc::Status::OK;
}

void FiberMaintServiceImpl::trend_task() {
    int interval_sec = Config::instance().get_int("trend.collect_interval_sec", 300);
    
    while (running_) {
        try {
            int32_t red_count = 0;
            int32_t yellow_count = 0;
            int32_t total_colored = 0;
            
            {
                std::lock_guard<std::mutex> lock(color_cache_mutex_);
                for (const auto& pair : color_by_fiber_) {
                    if (pair.second.color == fiber::common::FiberColor::RED) {
                        red_count++;
                    } else if (pair.second.color == fiber::common::FiberColor::YELLOW) {
                        yellow_count++;
                    }
                }
                total_colored = color_by_fiber_.size();
            }
            
            auto conn = DBConnectionPool::instance().get_connection();
            if (conn) {
                char sql[512];
                sprintf(sql, "INSERT INTO fiber_stats_trend (timestamp, red_count, yellow_count, total_colored) "
                             "VALUES (NOW(), %d, %d, %d)", red_count, yellow_count, total_colored);
                
                if (mysql_query(conn.get(), sql) == 0) {
                    Logger::instance().info("Trend stats collected: red={}, yellow={}, total={}", 
                                            red_count, yellow_count, total_colored);
                }
            }
        } catch (const std::exception& e) {
            Logger::instance().error("Trend task exception: {}", e.what());
        }
        
        std::this_thread::sleep_for(std::chrono::seconds(interval_sec));
    }
}

grpc::Status FiberMaintServiceImpl::GetFiberPerformance(grpc::ServerContext* context,
                                                        const fiber::maint::GetFiberPerformanceRequest* request,
                                                        fiber::maint::GetFiberPerformanceResponse* response) {
    FiberCacheEntry entry;
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        auto it = fiber_by_id_.find(request->fiber_id());
        if (it == fiber_by_id_.end()) {
            response->set_error_code(1);
            response->set_error_message("Fiber not found");
            return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
        }
        entry = it->second;
    }
    
    response->set_fiber_id(request->fiber_id());
    
    if (!entry.is_inter_ne) {
        response->set_error_code(2);
        response->set_error_message("Only inter-NE fibers supported");
        return grpc::Status(grpc::FAILED_PRECONDITION, "Only inter-NE fibers");
    }
    
    int32_t src_active_board = entry.src_board_id;
    int32_t dst_active_board = entry.dst_board_id;
    
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        
        auto port2_range = fiber_by_port_.equal_range({entry.src_board_id, 2});
        for (auto it = port2_range.first; it != port2_range.second; ++it) {
            int32_t f_id = it->second;
            auto f_it = fiber_by_id_.find(f_id);
            if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                src_active_board = (f_it->second.src_board_id == entry.src_board_id) 
                    ? f_it->second.dst_board_id : f_it->second.src_board_id;
                break;
            }
        }
        
        port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
        for (auto it = port2_range.first; it != port2_range.second; ++it) {
            int32_t f_id = it->second;
            auto f_it = fiber_by_id_.find(f_id);
            if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                dst_active_board = (f_it->second.src_board_id == entry.dst_board_id) 
                    ? f_it->second.dst_board_id : f_it->second.src_board_id;
                break;
            }
        }
    }
    
    double src_oop = 0.0;
    double dst_iop = 0.0;
    
    grpc::ClientContext ctx1;
    fiber::performance::GetCurrentPerformanceRequest perf_req1;
    perf_req1.set_board_id(src_active_board);
    perf_req1.set_port_id(1);
    fiber::performance::GetCurrentPerformanceResponse perf_resp1;
    
    auto status = perf_stub_->GetCurrentPerformance(&ctx1, perf_req1, &perf_resp1);
    if (status.ok()) {
        src_oop = perf_resp1.oop_value();
    }
    
    grpc::ClientContext ctx2;
    fiber::performance::GetCurrentPerformanceRequest perf_req2;
    perf_req2.set_board_id(dst_active_board);
    perf_req2.set_port_id(1);
    fiber::performance::GetCurrentPerformanceResponse perf_resp2;
    
    status = perf_stub_->GetCurrentPerformance(&ctx2, perf_req2, &perf_resp2);
    if (status.ok()) {
        dst_iop = perf_resp2.iop_value();
    }
    
    response->set_src_oop(src_oop);
    response->set_dst_iop(dst_iop);
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::BatchGetFiberPerformance(grpc::ServerContext* context,
                                                             const fiber::maint::BatchGetFiberPerformanceRequest* request,
                                                             fiber::maint::BatchGetFiberPerformanceResponse* response) {
    for (int32_t fiber_id : request->fiber_ids()) {
        auto result = response->add_results();
        result->set_found(false);
        result->set_fiber_id(fiber_id);
        
        FiberCacheEntry entry;
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(fiber_id);
            if (it == fiber_by_id_.end()) {
                result->set_error_message("Fiber not found");
                continue;
            }
            entry = it->second;
        }
        
        result->set_found(true);
        
        if (!entry.is_inter_ne) {
            result->set_error_code(2);
            result->set_error_message("Only inter-NE fibers supported");
            continue;
        }
        
        int32_t src_active_board = entry.src_board_id;
        int32_t dst_active_board = entry.dst_board_id;
        
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            
            auto port2_range = fiber_by_port_.equal_range({entry.src_board_id, 2});
            for (auto it = port2_range.first; it != port2_range.second; ++it) {
                int32_t f_id = it->second;
                auto f_it = fiber_by_id_.find(f_id);
                if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                    src_active_board = (f_it->second.src_board_id == entry.src_board_id) 
                        ? f_it->second.dst_board_id : f_it->second.src_board_id;
                    break;
                }
            }
            
            port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
            for (auto it = port2_range.first; it != port2_range.second; ++it) {
                int32_t f_id = it->second;
                auto f_it = fiber_by_id_.find(f_id);
                if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                    dst_active_board = (f_it->second.src_board_id == entry.dst_board_id) 
                        ? f_it->second.dst_board_id : f_it->second.src_board_id;
                    break;
                }
            }
        }
        
        double src_oop = 0.0;
        double dst_iop = 0.0;
        
        grpc::ClientContext ctx1;
        fiber::performance::GetCurrentPerformanceRequest perf_req1;
        perf_req1.set_board_id(src_active_board);
        perf_req1.set_port_id(1);
        fiber::performance::GetCurrentPerformanceResponse perf_resp1;
        
        auto status = perf_stub_->GetCurrentPerformance(&ctx1, perf_req1, &perf_resp1);
        if (status.ok()) {
            src_oop = perf_resp1.oop_value();
        }
        
        grpc::ClientContext ctx2;
        fiber::performance::GetCurrentPerformanceRequest perf_req2;
        perf_req2.set_board_id(dst_active_board);
        perf_req2.set_port_id(1);
        fiber::performance::GetCurrentPerformanceResponse perf_resp2;
        
        status = perf_stub_->GetCurrentPerformance(&ctx2, perf_req2, &perf_resp2);
        if (status.ok()) {
            dst_iop = perf_resp2.iop_value();
        }
        
        result->set_src_oop(src_oop);
        result->set_dst_iop(dst_iop);
    }
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberHistoryPerformance(grpc::ServerContext* context,
                                                               const fiber::maint::GetFiberHistoryPerformanceRequest* request,
                                                               fiber::maint::GetFiberHistoryPerformanceResponse* response) {
    FiberCacheEntry entry;
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        auto it = fiber_by_id_.find(request->fiber_id());
        if (it == fiber_by_id_.end()) {
            response->set_error_code(1);
            response->set_error_message("Fiber not found");
            return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
        }
        entry = it->second;
    }
    
    if (!entry.is_inter_ne) {
        response->set_error_code(2);
        response->set_error_message("Only inter-NE fibers supported");
        return grpc::Status(grpc::FAILED_PRECONDITION, "Only inter-NE fibers");
    }
    
    int32_t src_active_board = entry.src_board_id;
    int32_t dst_active_board = entry.dst_board_id;
    
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        
        auto port2_range = fiber_by_port_.equal_range({entry.src_board_id, 2});
        for (auto it = port2_range.first; it != port2_range.second; ++it) {
            int32_t f_id = it->second;
            auto f_it = fiber_by_id_.find(f_id);
            if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                src_active_board = (f_it->second.src_board_id == entry.src_board_id) 
                    ? f_it->second.dst_board_id : f_it->second.src_board_id;
                break;
            }
        }
        
        port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
        for (auto it = port2_range.first; it != port2_range.second; ++it) {
            int32_t f_id = it->second;
            auto f_it = fiber_by_id_.find(f_id);
            if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                dst_active_board = (f_it->second.src_board_id == entry.dst_board_id) 
                    ? f_it->second.dst_board_id : f_it->second.src_board_id;
                break;
            }
        }
    }
    
    grpc::ClientContext ctx1;
    fiber::performance::GetHistoryPerformanceRequest hist_req1;
    hist_req1.set_board_id(src_active_board);
    hist_req1.set_port_id(1);
    hist_req1.set_start_time(request->start_time());
    hist_req1.set_end_time(request->end_time());
    fiber::performance::GetHistoryPerformanceResponse hist_resp1;
    
    auto status = perf_stub_->GetHistoryPerformance(&ctx1, hist_req1, &hist_resp1);
    
    grpc::ClientContext ctx2;
    fiber::performance::GetHistoryPerformanceRequest hist_req2;
    hist_req2.set_board_id(dst_active_board);
    hist_req2.set_port_id(1);
    hist_req2.set_start_time(request->start_time());
    hist_req2.set_end_time(request->end_time());
    fiber::performance::GetHistoryPerformanceResponse hist_resp2;
    
    status = perf_stub_->GetHistoryPerformance(&ctx2, hist_req2, &hist_resp2);
    
    std::map<std::string, fiber::maint::FiberPerformanceRecord> record_map;
    
    for (const auto& rec : hist_resp1.records()) {
        auto it = record_map.find(rec.recorded_at());
        if (it == record_map.end()) {
            fiber::maint::FiberPerformanceRecord fr;
            fr.set_recorded_at(rec.recorded_at());
            fr.set_src_oop(rec.oop_value());
            record_map[rec.recorded_at()] = fr;
        } else {
            it->second.set_src_oop(rec.oop_value());
        }
    }
    
    for (const auto& rec : hist_resp2.records()) {
        auto it = record_map.find(rec.recorded_at());
        if (it == record_map.end()) {
            fiber::maint::FiberPerformanceRecord fr;
            fr.set_recorded_at(rec.recorded_at());
            fr.set_dst_iop(rec.iop_value());
            record_map[rec.recorded_at()] = fr;
        } else {
            it->second.set_dst_iop(rec.iop_value());
        }
    }
    
    for (const auto& pair : record_map) {
        *response->add_records() = pair.second;
    }
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::BatchGetFiberHistoryPerformance(grpc::ServerContext* context,
                                                                    const fiber::maint::BatchGetFiberHistoryPerformanceRequest* request,
                                                                    fiber::maint::BatchGetFiberHistoryPerformanceResponse* response) {
    for (int32_t fiber_id : request->fiber_ids()) {
        auto result = response->add_results();
        result->set_fiber_id(fiber_id);
        
        FiberCacheEntry entry;
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(fiber_id);
            if (it == fiber_by_id_.end()) {
                result->set_error_code(1);
                result->set_error_message("Fiber not found");
                continue;
            }
            entry = it->second;
        }
        
        if (!entry.is_inter_ne) {
            result->set_error_code(2);
            result->set_error_message("Only inter-NE fibers supported");
            continue;
        }
        
        int32_t src_active_board = entry.src_board_id;
        int32_t dst_active_board = entry.dst_board_id;
        
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            
            auto port2_range = fiber_by_port_.equal_range({entry.src_board_id, 2});
            for (auto it = port2_range.first; it != port2_range.second; ++it) {
                int32_t f_id = it->second;
                auto f_it = fiber_by_id_.find(f_id);
                if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                    src_active_board = (f_it->second.src_board_id == entry.src_board_id) 
                        ? f_it->second.dst_board_id : f_it->second.src_board_id;
                    break;
                }
            }
            
            port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
            for (auto it = port2_range.first; it != port2_range.second; ++it) {
                int32_t f_id = it->second;
                auto f_it = fiber_by_id_.find(f_id);
                if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                    dst_active_board = (f_it->second.src_board_id == entry.dst_board_id) 
                        ? f_it->second.dst_board_id : f_it->second.src_board_id;
                    break;
                }
            }
        }
        
        grpc::ClientContext ctx1;
        fiber::performance::GetHistoryPerformanceRequest hist_req1;
        hist_req1.set_board_id(src_active_board);
        hist_req1.set_port_id(1);
        hist_req1.set_start_time(request->start_time());
        hist_req1.set_end_time(request->end_time());
        fiber::performance::GetHistoryPerformanceResponse hist_resp1;
        
        auto status = perf_stub_->GetHistoryPerformance(&ctx1, hist_req1, &hist_resp1);
        
        grpc::ClientContext ctx2;
        fiber::performance::GetHistoryPerformanceRequest hist_req2;
        hist_req2.set_board_id(dst_active_board);
        hist_req2.set_port_id(1);
        hist_req2.set_start_time(request->start_time());
        hist_req2.set_end_time(request->end_time());
        fiber::performance::GetHistoryPerformanceResponse hist_resp2;
        
        status = perf_stub_->GetHistoryPerformance(&ctx2, hist_req2, &hist_resp2);
        
        std::map<std::string, fiber::maint::FiberPerformanceRecord> record_map;
        
        for (const auto& rec : hist_resp1.records()) {
            auto it = record_map.find(rec.recorded_at());
            if (it == record_map.end()) {
                fiber::maint::FiberPerformanceRecord fr;
                fr.set_recorded_at(rec.recorded_at());
                fr.set_src_oop(rec.oop_value());
                record_map[rec.recorded_at()] = fr;
            } else {
                it->second.set_src_oop(rec.oop_value());
            }
        }
        
        for (const auto& rec : hist_resp2.records()) {
            auto it = record_map.find(rec.recorded_at());
            if (it == record_map.end()) {
                fiber::maint::FiberPerformanceRecord fr;
                fr.set_recorded_at(rec.recorded_at());
                fr.set_dst_iop(rec.iop_value());
                record_map[rec.recorded_at()] = fr;
            } else {
                it->second.set_dst_iop(rec.iop_value());
            }
        }
        
        for (const auto& pair : record_map) {
            *result->add_records() = pair.second;
        }
    }
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberSpanloss(grpc::ServerContext* context,
                                                     const fiber::maint::GetFiberSpanlossRequest* request,
                                                     fiber::maint::GetFiberSpanlossResponse* response) {
    FiberCacheEntry entry;
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        auto it = fiber_by_id_.find(request->fiber_id());
        if (it == fiber_by_id_.end()) {
            return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
        }
        entry = it->second;
    }
    
    response->set_fiber_id(request->fiber_id());
    
    if (!entry.is_inter_ne) {
        response->set_spanloss(0.0);
        return grpc::Status::OK;
    }
    
    int32_t src_active_board = entry.src_board_id;
    int32_t dst_active_board = entry.dst_board_id;
    
    {
        std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
        
        auto port2_range = fiber_by_port_.equal_range({entry.src_board_id, 2});
        for (auto it = port2_range.first; it != port2_range.second; ++it) {
            int32_t f_id = it->second;
            auto f_it = fiber_by_id_.find(f_id);
            if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                src_active_board = (f_it->second.src_board_id == entry.src_board_id) 
                    ? f_it->second.dst_board_id : f_it->second.src_board_id;
                break;
            }
        }
        
        port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
        for (auto it = port2_range.first; it != port2_range.second; ++it) {
            int32_t f_id = it->second;
            auto f_it = fiber_by_id_.find(f_id);
            if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                dst_active_board = (f_it->second.src_board_id == entry.dst_board_id) 
                    ? f_it->second.dst_board_id : f_it->second.src_board_id;
                break;
            }
        }
    }
    
    double src_oop = 0.0;
    double dst_iop = 0.0;
    
    grpc::ClientContext ctx1;
    fiber::performance::GetCurrentPerformanceRequest perf_req1;
    perf_req1.set_board_id(src_active_board);
    perf_req1.set_port_id(1);
    fiber::performance::GetCurrentPerformanceResponse perf_resp1;
    
    auto status = perf_stub_->GetCurrentPerformance(&ctx1, perf_req1, &perf_resp1);
    if (status.ok()) {
        src_oop = perf_resp1.oop_value();
    }
    
    grpc::ClientContext ctx2;
    fiber::performance::GetCurrentPerformanceRequest perf_req2;
    perf_req2.set_board_id(dst_active_board);
    perf_req2.set_port_id(1);
    fiber::performance::GetCurrentPerformanceResponse perf_resp2;
    
    status = perf_stub_->GetCurrentPerformance(&ctx2, perf_req2, &perf_resp2);
    if (status.ok()) {
        dst_iop = perf_resp2.iop_value();
    }
    
    double spanloss = src_oop - dst_iop;
    response->set_spanloss(spanloss);
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::BatchGetFiberSpanloss(grpc::ServerContext* context,
                                                          const fiber::maint::BatchGetFiberSpanlossRequest* request,
                                                          fiber::maint::BatchGetFiberSpanlossResponse* response) {
    for (int32_t fiber_id : request->fiber_ids()) {
        auto result = response->add_results();
        result->set_found(false);
        result->set_fiber_id(fiber_id);
        result->set_spanloss(0.0);
        
        FiberCacheEntry entry;
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(fiber_id);
            if (it == fiber_by_id_.end()) {
                result->set_error_message("Fiber not found");
                continue;
            }
            entry = it->second;
        }
        
        result->set_found(true);
        
        if (!entry.is_inter_ne) {
            continue;
        }
        
        int32_t src_active_board = entry.src_board_id;
        int32_t dst_active_board = entry.dst_board_id;
        
        {
            std::lock_guard<std::mutex> lock(fiber_cache_mutex_);
            
            auto port2_range = fiber_by_port_.equal_range({entry.src_board_id, 2});
            for (auto it = port2_range.first; it != port2_range.second; ++it) {
                int32_t f_id = it->second;
                auto f_it = fiber_by_id_.find(f_id);
                if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                    src_active_board = (f_it->second.src_board_id == entry.src_board_id) 
                        ? f_it->second.dst_board_id : f_it->second.src_board_id;
                    break;
                }
            }
            
            port2_range = fiber_by_port_.equal_range({entry.dst_board_id, 2});
            for (auto it = port2_range.first; it != port2_range.second; ++it) {
                int32_t f_id = it->second;
                auto f_it = fiber_by_id_.find(f_id);
                if (f_it != fiber_by_id_.end() && !f_it->second.is_inter_ne) {
                    dst_active_board = (f_it->second.src_board_id == entry.dst_board_id) 
                        ? f_it->second.dst_board_id : f_it->second.src_board_id;
                    break;
                }
            }
        }
        
        double src_oop = 0.0;
        double dst_iop = 0.0;
        
        grpc::ClientContext ctx1;
        fiber::performance::GetCurrentPerformanceRequest perf_req1;
        perf_req1.set_board_id(src_active_board);
        perf_req1.set_port_id(1);
        fiber::performance::GetCurrentPerformanceResponse perf_resp1;
        
        auto status = perf_stub_->GetCurrentPerformance(&ctx1, perf_req1, &perf_resp1);
        if (status.ok()) {
            src_oop = perf_resp1.oop_value();
        }
        
        grpc::ClientContext ctx2;
        fiber::performance::GetCurrentPerformanceRequest perf_req2;
        perf_req2.set_board_id(dst_active_board);
        perf_req2.set_port_id(1);
        fiber::performance::GetCurrentPerformanceResponse perf_resp2;
        
        status = perf_stub_->GetCurrentPerformance(&ctx2, perf_req2, &perf_resp2);
        if (status.ok()) {
            dst_iop = perf_resp2.iop_value();
        }
        
        double spanloss = src_oop - dst_iop;
        result->set_spanloss(spanloss);
    }
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetColoredFibers(grpc::ServerContext* context,
                                                     const fiber::maint::GetColoredFibersRequest* request,
                                                     fiber::maint::GetColoredFibersResponse* response) {
    std::lock_guard<std::mutex> lock(color_cache_mutex_);
    
    for (const auto& pair : color_by_fiber_) {
        int32_t fiber_id = pair.first;
        const auto& color_entry = pair.second;
        
        if (color_entry.color != request->color()) continue;
        
        FiberCacheEntry fiber_entry;
        {
            std::lock_guard<std::mutex> lock2(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(fiber_id);
            if (it == fiber_by_id_.end()) continue;
            fiber_entry = it->second;
        }
        
        auto info = response->add_fibers();
        
        fiber::common::FiberInfo fiber_info;
        fiber_info.set_fiber_id(fiber_entry.fiber_id);
        fiber_info.set_src_board_id(fiber_entry.src_board_id);
        fiber_info.set_src_port_id(fiber_entry.src_port_id);
        fiber_info.set_src_ne_id(fiber_entry.src_ne_id);
        fiber_info.set_dst_board_id(fiber_entry.dst_board_id);
        fiber_info.set_dst_port_id(fiber_entry.dst_port_id);
        fiber_info.set_dst_ne_id(fiber_entry.dst_ne_id);
        
        *info->mutable_fiber() = fiber_info;
        info->set_color(static_cast<fiber::common::FiberColor>(color_entry.color));
    }
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetAllColoredFibers(grpc::ServerContext* context,
                                                        const fiber::maint::GetAllColoredFibersRequest* request,
                                                        fiber::maint::GetAllColoredFibersResponse* response) {
    std::lock_guard<std::mutex> lock(color_cache_mutex_);

    for (const auto& pair : color_by_fiber_) {
        int32_t fiber_id = pair.first;
        const auto& color_entry = pair.second;

        if (color_entry.color != fiber::common::FiberColor::RED &&
            color_entry.color != fiber::common::FiberColor::YELLOW) {
            continue;
        }

        FiberCacheEntry fiber_entry;
        {
            std::lock_guard<std::mutex> lock2(fiber_cache_mutex_);
            auto it = fiber_by_id_.find(fiber_id);
            if (it == fiber_by_id_.end()) continue;
            fiber_entry = it->second;
        }

        auto info = response->add_fibers();
        fiber::common::FiberInfo fiber_info;
        fiber_info.set_fiber_id(fiber_entry.fiber_id);
        fiber_info.set_src_board_id(fiber_entry.src_board_id);
        fiber_info.set_src_port_id(fiber_entry.src_port_id);
        fiber_info.set_src_ne_id(fiber_entry.src_ne_id);
        fiber_info.set_dst_board_id(fiber_entry.dst_board_id);
        fiber_info.set_dst_port_id(fiber_entry.dst_port_id);
        fiber_info.set_dst_ne_id(fiber_entry.dst_ne_id);
        *info->mutable_fiber() = fiber_info;
        info->set_color(static_cast<fiber::common::FiberColor>(color_entry.color));
        info->set_scene_type(color_entry.scene_type);
    }

    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberStatsRealtime(grpc::ServerContext* context,
                                                         const fiber::maint::GetFiberStatsRealtimeRequest* request,
                                                         fiber::maint::GetFiberStatsRealtimeResponse* response) {
    std::lock_guard<std::mutex> lock(color_cache_mutex_);
    
    int32_t red_count = 0, yellow_count = 0, green_count = 0;
    
    for (const auto& pair : color_by_fiber_) {
        const auto& color_entry = pair.second;
        
        if (color_entry.color == fiber::common::FiberColor::RED) red_count++;
        else if (color_entry.color == fiber::common::FiberColor::YELLOW) yellow_count++;
        else if (color_entry.color == fiber::common::FiberColor::GREEN) green_count++;
    }
    
    response->set_red_count(red_count);
    response->set_yellow_count(yellow_count);
    response->set_green_count(green_count);
    response->set_total_fibers(fiber_by_id_.size());
    
    response->set_active_alarms(alarm_cache_.size());
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberStatsTrend(grpc::ServerContext* context,
                                                       const fiber::maint::GetFiberStatsTrendRequest* request,
                                                       fiber::maint::GetFiberStatsTrendResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    char sql[512];
    sprintf(sql, "SELECT timestamp, red_count, yellow_count, total_colored FROM fiber_stats_trend "
                 "WHERE timestamp BETWEEN '%s' AND '%s' ORDER BY timestamp",
            request->start_time().c_str(), request->end_time().c_str());
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        auto point = response->add_points();
        point->set_timestamp(row[0]);
        point->set_red_count(std::stoi(row[1]));
        point->set_yellow_count(std::stoi(row[2]));
        point->set_total_colored(std::stoi(row[3]));
    }
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::HealthCheck(grpc::ServerContext* context,
                                                const fiber::maint::HealthCheckRequest* request,
                                                fiber::common::HealthCheckResponse* response) {
    response->set_serving(true);
    response->set_version("1.0.0");
    return grpc::Status::OK;
}