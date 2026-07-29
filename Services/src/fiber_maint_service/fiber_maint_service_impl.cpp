/**
 * @file fiber_maint_service_impl.cpp
 * @brief FiberMaintService v4.0 — 重构实现
 *
 * 核心变更：
 * - 4 mutex → 1 shared_mutex（cache_rw_mutex_）
 * - worker_threads_ → event_process_thread_（单线程事件驱动）
 * - find_affected_fibers() → dep_builder_.lookup() (O(1))
 * - calculate_color() → ScenarioRegistry + IColorStrategy
 * - GetFiberPerformance/Spanloss → L1 Resolver → L2 Builder → L3 Executor
 * - Phase 2: 指数退避断线重连 + 优雅关闭 + OutputThread + FlapDetector
 */

#include "fiber_maint_service_impl.h"

using namespace fiber_maint;

// ============================================================
//  构造 / 析构 / 初始化
// ============================================================

FiberMaintServiceImpl::FiberMaintServiceImpl() : running_(true) {}

FiberMaintServiceImpl::~FiberMaintServiceImpl() {
    running_ = false;

    // Phase 2.7: 优雅关闭 — 分阶段停止
    // Stage 1: 唤醒事件处理线程
    event_queue_.push_full_sync_done();

    // Stage 2: 停止 gRPC 订阅线程（最多 5s）
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    auto wait_join = [&](std::thread& t) {
        if (t.joinable()) {
            if (std::chrono::steady_clock::now() < deadline) {
                t.join();
            } else {
                t.detach();
            }
        }
    };

    wait_join(alarm_sub_thread_);
    wait_join(fiber_sub_thread_);

    // Stage 3: 停止事件处理线程
    if (event_process_thread_.joinable()) {
        event_process_thread_.join();
    }

    // Stage 4: 刷写输出层（最多 10s）
    output_thread_.shutdown();

    // Stage 5: 停止趋势采集
    if (trend_thread_.joinable()) {
        trend_thread_.join();
    }

    Logger::instance().info("FiberMaintService v4.0 graceful shutdown complete");
}

bool FiberMaintServiceImpl::init() {
    Logger::instance().info("FiberMaintService v4.0 initializing");
    Config& config = Config::instance();
    std::string host = config.get_string("db.host", "localhost");
    int port = config.get_int("db.port", 3306);
    std::string user = config.get_string("db.user", "root");
    std::string password = config.get_string("db.password", "");
    std::string database = config.get_string("db.database", "db_fiber_maint");

    if (!DBConnectionPool::instance().init(host, port, user, password, database)) {
        Logger::instance().error("DBConnectionPool init failed");
        return false;
    }

    std::string alarm_addr    = config.get_string("alarm_service.addr", "localhost:50054");
    std::string topology_addr = config.get_string("topology_service.addr", "localhost:50062");
    std::string perf_addr     = config.get_string("performance_service.addr", "localhost:50053");

    alarm_stub_    = fiber::alarm::AlarmService::NewStub(
        grpc::CreateChannel(alarm_addr, grpc::InsecureChannelCredentials()));
    topology_stub_ = fiber::topology::TopologyService::NewStub(
        grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials()));
    perf_stub_     = fiber::performance::PerformanceService::NewStub(
        grpc::CreateChannel(perf_addr, grpc::InsecureChannelCredentials()));

    perf_executor_ = std::make_unique<PerfQueryExecutor>(perf_stub_);
    spanloss_calc_ = std::make_unique<SpanlossCalculator>(perf_stub_);

    sync_fiber_cache();

    {
        std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
        fiber_by_id_.reserve(1200000);
        fiber_by_port_.reserve(2400000);
        alarm_cache_.reserve(500000);
        color_by_fiber_.reserve(100000);
        color_contexts_.reserve(1000000);
    }

    sync_color_cache();

    resolver_.bind(&fiber_by_id_, &fiber_by_port_, &cache_rw_mutex_);
    dep_builder_.bind(&fiber_by_id_, &fiber_by_port_, &cache_rw_mutex_);
    dep_builder_.build_all();

    // Phase 2: 绑定输出层
    output_thread_.bind(&output_queue_, &cache_rw_mutex_, &color_contexts_);
    output_thread_.set_push_callback([this](const ChangeRecord& rec) {
        fiber::maint::FiberColorEvent event;
        event.set_fiber_id(rec.fiber_id);
        event.set_old_color(static_cast<fiber::common::FiberColor>(rec.old_color));
        event.set_new_color(static_cast<fiber::common::FiberColor>(rec.new_color));
        push_color_event(event);
    });

    // Phase 2: 绑定 Pull Callback
    pull_callback_.bind(alarm_stub_, &alarm_cache_, &cache_rw_mutex_,
                        &event_queue_, get_callback_addr());

    event_process_thread_ = std::thread(&FiberMaintServiceImpl::event_process_loop, this);
    alarm_sub_thread_     = std::thread(&FiberMaintServiceImpl::subscribe_alarm_events, this);
    fiber_sub_thread_     = std::thread(&FiberMaintServiceImpl::subscribe_fiber_events, this);
    trend_thread_         = std::thread(&FiberMaintServiceImpl::trend_task, this);
    output_thread_.start(&running_);
    pull_callback_.start(&running_);

    sync_state_.store(SyncState::STREAMING);
    Logger::instance().info("FiberMaintService v4.0 initialized");
    return true;
}

std::string FiberMaintServiceImpl::get_callback_addr() {
    Config& config = Config::instance();
    std::string callback_addr = config.get_string("callback_service_addr", "");
    if (!callback_addr.empty()) return callback_addr;
    return config.get_string("server.addr", "localhost:50051");
}

void FiberMaintServiceImpl::init_alarm_sync_async() {
    Logger::instance().info("init_alarm_sync_async: delegated to PullCallbackThread");
}

void FiberMaintServiceImpl::sync_alarm_cache() {
    pull_callback_.resync();
}

void FiberMaintServiceImpl::sync_fiber_cache() {
    fiber::topology::BatchGetFibersRequest req;
    grpc::ClientContext ctx;
    fiber::topology::BatchGetFibersResponse resp;

    Logger::instance().info("Syncing fiber cache");
    auto status = topology_stub_->BatchGetFibers(&ctx, req, &resp);
    if (!status.ok()) {
        Logger::instance().error("BatchGetFibers failed: {}", status.error_message());
        return;
    }

    std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
    fiber_by_id_.clear();
    fiber_by_port_.clear();

    for (const auto& result : resp.results()) {
        if (!result.found()) continue;
        const auto& fiber = result.fiber();
        FiberCacheEntry entry{
            fiber.fiber_id(),
            fiber.src_board_id(), fiber.src_port_id(), fiber.src_ne_id(),
            fiber.dst_board_id(), fiber.dst_port_id(), fiber.dst_ne_id(),
            fiber.src_ne_id() != fiber.dst_ne_id()
        };
        fiber_by_id_[entry.fiber_id] = entry;
        fiber_by_port_.insert({{entry.src_board_id, entry.src_port_id}, entry.fiber_id});
        fiber_by_port_.insert({{entry.dst_board_id, entry.dst_port_id}, entry.fiber_id});
    }
    Logger::instance().info("Fiber cache synced, {} entries", fiber_by_id_.size());
}

void FiberMaintServiceImpl::sync_color_cache() {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        Logger::instance().error("DBConnectionPool get_connection failed");
        return;
    }
    std::string sql = "SELECT fiber_id, color, scene_type FROM fiber_colors WHERE color IN (2, 3)";
    if (mysql_query(conn.get(), sql.c_str()) != 0) {
        Logger::instance().error("MySQL query failed: {}", mysql_error(conn.get()));
        return;
    }
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
    color_by_fiber_.clear();
    while ((row = mysql_fetch_row(res)) != nullptr) {
        int8_t color = static_cast<int8_t>(std::stoi(row[1]));
        FiberColorCacheEntry entry{color, row[2] ? std::stoi(row[2]) : 0};
        color_by_fiber_[std::stoi(row[0])] = entry;
    }
    mysql_free_result(res);
    Logger::instance().info("Color cache synced, {} entries", color_by_fiber_.size());
}

void FiberMaintServiceImpl::full_color_recalc() {
    std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
    Logger::instance().info("Full color recalculation started");
    for (const auto& [fid, entry] : fiber_by_id_) {
        if (!entry.is_inter_ne) continue;
        lock.unlock();
        recalculate_fiber_color(fid);
        lock.lock();
    }
    Logger::instance().info("Full color recalculation completed");
}

// ============================================================
//  Phase 2.4-2.5: 断线重连（指数退避 5s→10s→20s→40s→60s cap）
// ============================================================

void FiberMaintServiceImpl::subscribe_alarm_events() {
    constexpr int BASE_DELAY_SEC = 5;
    constexpr int MAX_DELAY_SEC  = 60;
    int delay_sec = BASE_DELAY_SEC;

    while (running_) {
        grpc::ClientContext ctx;
        fiber::alarm::SubscribeAlarmEventsRequest req;
        auto reader = alarm_stub_->SubscribeAlarmEvents(&ctx, req);

        if (!reader) {
            Logger::instance().error("Alarm stream: failed, retry in {}s", delay_sec);
            std::this_thread::sleep_for(std::chrono::seconds(delay_sec));
            delay_sec = std::min(delay_sec * 2, MAX_DELAY_SEC);
            continue;
        }

        Logger::instance().info("Alarm stream connected");
        delay_sec = BASE_DELAY_SEC;

        fiber::alarm::AlarmEvent event;
        while (reader->Read(&event)) {
            if (!running_) return;
            process_alarm_event(event);
        }

        Logger::instance().warn("Alarm stream disconnected, reconnecting in {}s...", delay_sec);
        std::this_thread::sleep_for(std::chrono::seconds(delay_sec));
        delay_sec = std::min(delay_sec * 2, MAX_DELAY_SEC);

        if (running_) {
            sync_state_.store(SyncState::STREAMING);
            pull_callback_.resync();
        }
    }
}

void FiberMaintServiceImpl::subscribe_fiber_events() {
    constexpr int BASE_DELAY_SEC = 5;
    constexpr int MAX_DELAY_SEC  = 60;
    int delay_sec = BASE_DELAY_SEC;

    while (running_) {
        grpc::ClientContext ctx;
        fiber::topology::SubscribeFiberEventsRequest req;
        auto reader = topology_stub_->SubscribeFiberEvents(&ctx, req);

        if (!reader) {
            Logger::instance().error("Fiber stream: failed, retry in {}s", delay_sec);
            std::this_thread::sleep_for(std::chrono::seconds(delay_sec));
            delay_sec = std::min(delay_sec * 2, MAX_DELAY_SEC);
            continue;
        }

        Logger::instance().info("Fiber stream connected");
        delay_sec = BASE_DELAY_SEC;

        fiber::topology::FiberEvent event;
        while (reader->Read(&event)) {
            if (!running_) return;
            Logger::instance().info("get fiber event");
            process_fiber_event(event);
        }

        Logger::instance().warn("Fiber stream disconnected, reconnecting in {}s...", delay_sec);
        std::this_thread::sleep_for(std::chrono::seconds(delay_sec));
        delay_sec = std::min(delay_sec * 2, MAX_DELAY_SEC);

        if (running_) {
            sync_fiber_cache();
            dep_builder_.build_all();
            full_color_recalc();
        }
    }
}

void FiberMaintServiceImpl::process_alarm_event(
        const fiber::alarm::AlarmEvent& event) {
    {
        std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
        AlarmCacheKey key{event.board_id(), event.port_id(),
            static_cast<int8_t>(event.alarm_level())};
        if (event.event_type() == fiber::common::ALARM_RAISED)
            alarm_cache_[key] = {event.timestamp()};
        else
            alarm_cache_.erase(key);
    }
    QueueEvent qe;
    qe.type = EventType::ALARM_EVENT;
    qe.board_id = event.board_id();
    qe.port_id = event.port_id();
    qe.alarm_level = static_cast<int8_t>(event.alarm_level());
    qe.is_raise = (event.event_type() == fiber::common::ALARM_RAISED);

    std::string strAlarmType = event.event_type() == fiber::common::ALARM_RAISED ? "RAISED" : "Cleared";
    Logger::instance().info("[{}]get alarm event {} {} {}", strAlarmType, qe.board_id, qe.port_id, AlarmLevelStr[qe.alarm_level]);
    event_queue_.push_alarm(std::move(qe));
}

void FiberMaintServiceImpl::process_fiber_event(
        const fiber::topology::FiberEvent& event) {
    int32_t fid = event.fiber_id();
    bool is_inter_ne = false;

    {
        std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
        Logger::instance().info("process_fiber_event {} {}", fid, event.event_type());
        if (event.event_type() == fiber::common::FIBER_CREATED) {
            // Fetch full fiber info from topology service
            grpc::ClientContext ctx;
            fiber::topology::GetFiberRequest req;
            req.set_fiber_id(fid);
            fiber::topology::GetFiberResponse resp;
            auto status = topology_stub_->GetFiber(&ctx, req, &resp);
            if (status.ok()) {
                const auto& fiber = resp.fiber();
                is_inter_ne = fiber.src_ne_id() != fiber.dst_ne_id();
                FiberCacheEntry entry{
                    fiber.fiber_id(),
                    fiber.src_board_id(), fiber.src_port_id(), fiber.src_ne_id(),
                    fiber.dst_board_id(), fiber.dst_port_id(), fiber.dst_ne_id(),
                    is_inter_ne
                };
                fiber_by_id_[entry.fiber_id] = entry;
                fiber_by_port_.insert({{entry.src_board_id, entry.src_port_id}, entry.fiber_id});
                fiber_by_port_.insert({{entry.dst_board_id, entry.dst_port_id}, entry.fiber_id});
            }
        } else if (event.event_type() == fiber::common::FIBER_DELETED) {
            auto it = fiber_by_id_.find(fid);
            if (it != fiber_by_id_.end()) {
                is_inter_ne = it->second.is_inter_ne;
                fiber_by_port_.erase({it->second.src_board_id, it->second.src_port_id});
                fiber_by_port_.erase({it->second.dst_board_id, it->second.dst_port_id});
                fiber_by_id_.erase(it);
            }
        }
    }
    QueueEvent qe;
    qe.type = EventType::FIBER_EVENT;
    qe.fiber_id = fid;
    qe.is_inter_ne = is_inter_ne;
    std::string strEventType = event.event_type() == fiber::common::FIBER_CREATED ? "CREATED" : "DELETED";
    Logger::instance().info("[{}]get fiber event {} {}", strEventType, qe.fiber_id, qe.is_inter_ne);
    event_queue_.push_fiber(std::move(qe));
}

void FiberMaintServiceImpl::event_process_loop() {
    while (running_) {
        EventBatch batch = event_queue_.drain(running_);
        if (!running_ && batch.alarm_events.empty()
                     && batch.fiber_events.empty()
                     && !batch.full_sync_done) break;

        std::unordered_set<int32_t> affected_fibers;
        for (const auto& ae : batch.alarm_events) {
            auto deps = dep_builder_.lookup({ae.board_id, ae.port_id});
            for (size_t i = 0; i < deps.size(); ++i){
                Logger::instance().info("EventProcessLoop: dependency {} {}, affected_fiber {}", ae.board_id, ae.port_id, deps[i].fiber_id);
                affected_fibers.insert(deps[i].fiber_id);
            }
        }
        for (const auto& fe : batch.fiber_events) {
            dep_builder_.rebuild(fe.fiber_id);
            if (fe.is_inter_ne) affected_fibers.insert(fe.fiber_id);
            auto topo = resolver_.resolve(fe.fiber_id);
            if (!topo.is_inter_ne) {
                auto inter = resolver_.get_inter_ne_fibers_by_port({topo.src.board_id, 1});
                for (int32_t fid : inter) { affected_fibers.insert(fid); dep_builder_.rebuild(fid); }
            }
        }
        if (batch.full_sync_done) {
            sync_state_.store(SyncState::SYNCED);
            full_color_recalc();
            continue;
        }
        for (int32_t fid : affected_fibers) {
            if (flap_detector_.record_change(fid))
                recalculate_fiber_color(fid);
        }
        static int lc = 0;
        if (++lc % 1000 == 0) flap_detector_.cleanup();
    }
}

int8_t FiberMaintServiceImpl::calculate_color(
        int32_t fiber_id, int32_t& scene_type, int32_t& scenario_case) {
    auto topo = resolver_.resolve(fiber_id);
    if (!topo.is_inter_ne) { scene_type = 0; scenario_case = 0; return static_cast<int8_t>(FiberColor::GREEN); }
    auto targets = AlarmTargetBuilder::build(topo);
    ColorEvalInput input; input.topo = topo;
    for (const auto& target : targets) {
        PortAlarmStatus alarm_status;
        {
            std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
            AlarmCacheKey ck{target.board_id, target.port_id, static_cast<int8_t>(fiber::common::AlarmLevel::CRITICAL)};
            AlarmCacheKey mk{target.board_id, target.port_id, static_cast<int8_t>(fiber::common::AlarmLevel::MINOR)};
            alarm_status.has_critical = alarm_cache_.count(ck) > 0;
            alarm_status.has_minor = alarm_cache_.count(mk) > 0;
        }
        input.alarm_statuses.push_back({target.role, alarm_status});
    }
    const IColorStrategy* strategy = registry_.match(topo);
    if (strategy->can_skip(input)) {
        scene_type = static_cast<int32_t>(topo.scene_type);
        scenario_case = static_cast<int32_t>(topo.scenario_case);
        return static_cast<int8_t>(FiberColor::GREEN);
    }
    FiberColor color = strategy->evaluate(input);
    scene_type = static_cast<int32_t>(topo.scene_type);
    scenario_case = static_cast<int32_t>(topo.scenario_case);
    if (color != FiberColor::GREEN)
    {
        Logger::instance().info("calculate_color {} {} {}", fiber_id, FiberColorStr[static_cast<int8_t>(color)], std::to_string(scene_type));
    }

    return static_cast<int8_t>(color);
}

void FiberMaintServiceImpl::recalculate_fiber_color(int32_t fiber_id) {
    int32_t st = 0, sc = 0;
    int8_t nc = calculate_color(fiber_id, st, sc);
    update_fiber_color(fiber_id, nc, st, sc);
}

void FiberMaintServiceImpl::update_fiber_color(
        int32_t fiber_id, int8_t new_color, int32_t scene_type, int32_t scenario_case) {
    int8_t old_color = static_cast<int8_t>(FiberColor::GREEN);
    {
        std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
        auto it = color_by_fiber_.find(fiber_id);
        if (it != color_by_fiber_.end()) old_color = it->second.color;
        color_by_fiber_[fiber_id] = {new_color, scene_type};
        color_contexts_[fiber_id] = {
            static_cast<FiberColor>(new_color), static_cast<SceneType>(scene_type),
            static_cast<ScenarioCase>(scenario_case), 0, 0,
            std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count()
        };
    }
    if (old_color != new_color) {
        ChangeRecord rec;
        rec.fiber_id = fiber_id;
        rec.old_color = static_cast<FiberColor>(old_color);
        rec.new_color = static_cast<FiberColor>(new_color);
        rec.scene_type = static_cast<SceneType>(scene_type);
        rec.scenario_case = static_cast<ScenarioCase>(scenario_case);
        rec.timestamp_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        output_thread_.enqueue(std::move(rec));

        fiber::maint::FiberColorEvent event;
        event.set_fiber_id(fiber_id);
        event.set_old_color(static_cast<fiber::common::FiberColor>(old_color));
        event.set_new_color(static_cast<fiber::common::FiberColor>(new_color));
        event.set_scene_type(scene_type);
        event.set_scenario_case(scenario_case);
        {
            std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
            auto f_it = fiber_by_id_.find(fiber_id);
            if (f_it != fiber_by_id_.end()) {
                auto* fi = event.mutable_fiber();
                fi->set_fiber_id(f_it->second.fiber_id);
                fi->set_src_board_id(f_it->second.src_board_id);
                fi->set_src_port_id(f_it->second.src_port_id);
                fi->set_src_ne_id(f_it->second.src_ne_id);
                fi->set_dst_board_id(f_it->second.dst_board_id);
                fi->set_dst_port_id(f_it->second.dst_port_id);
                fi->set_dst_ne_id(f_it->second.dst_ne_id);
            }
        }
        push_color_event(event);
        Logger::instance().info("{} fiber_color change from {} to {}", fiber_id, FiberColorStr[old_color], FiberColorStr[new_color]);
    }
    else 
    {
        if (old_color != static_cast<int8_t>(FiberColor::GREEN))
            Logger::instance().info("{} fiber_color still {}", fiber_id, FiberColorStr[old_color]);
    }
}

void FiberMaintServiceImpl::init_fiber_color(const FiberCacheEntry& entry) {
    if (!entry.is_inter_ne) return;
    int32_t st = 0, sc = 0;
    update_fiber_color(entry.fiber_id, calculate_color(entry.fiber_id, st, sc), st, sc);
}

bool FiberMaintServiceImpl::has_alarm(int32_t board_id, int32_t port_id, int8_t alarm_level) {
    std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
    return alarm_cache_.count({board_id, port_id, alarm_level}) > 0;
}

PortAlarmSummary FiberMaintServiceImpl::get_port_alarm_summary(int32_t board_id, int32_t port_id) {
    return {
        .has_critical = has_alarm(board_id, port_id, static_cast<int8_t>(fiber::common::AlarmLevel::CRITICAL)),
        .has_minor = has_alarm(board_id, port_id, static_cast<int8_t>(fiber::common::AlarmLevel::MINOR))
    };
}

void FiberMaintServiceImpl::push_color_event(const fiber::maint::FiberColorEvent& event) {
    std::lock_guard<std::mutex> lock(writer_mutex_);
    for (size_t i = 0; i < color_event_writers_.size(); ) {
        if (!color_event_writers_[i]->Write(event))
            color_event_writers_.erase(color_event_writers_.begin() + i);
        else ++i;
    }
}

void FiberMaintServiceImpl::trend_task() {
    int interval_sec = Config::instance().get_int("trend_interval_seconds", 300);
    while (running_) {
        try {
            int32_t r = 0, y = 0, g = 0;
            {
                std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
                for (const auto& [fid, ce] : color_by_fiber_) {
                    if (ce.color == static_cast<int8_t>(FiberColor::RED)) r++;
                    else if (ce.color == static_cast<int8_t>(FiberColor::YELLOW)) y++;
                    else if (ce.color == static_cast<int8_t>(FiberColor::GREEN)) g++;
                }
            }
            auto conn = DBConnectionPool::instance().get_connection();
            if (conn) {
                std::string sql = "INSERT INTO fiber_stats_trend (timestamp,red_count,yellow_count,green_count,total_colored) VALUES (NOW()," +
                    std::to_string(r) + "," + std::to_string(y) + "," + std::to_string(g) + "," + std::to_string(r+y+g) + ")";
                mysql_query(conn.get(), sql.c_str());
            }
        } catch (const std::exception& e) {
            Logger::instance().error("Trend task exception: {}", e.what());
        }
        for (int i = 0; i < interval_sec && running_; ++i)
            std::this_thread::sleep_for(std::chrono::seconds(1));
    }
}

grpc::Status FiberMaintServiceImpl::GetFiberPerformance(grpc::ServerContext*, const fiber::maint::GetFiberPerformanceRequest* req, fiber::maint::GetFiberPerformanceResponse* resp) {
    resp->set_fiber_id(req->fiber_id());
    auto topo = resolver_.resolve(req->fiber_id());
    if (topo.fiber_id == 0) return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
    if (!topo.is_inter_ne) return grpc::Status(grpc::FAILED_PRECONDITION, "Only inter-NE");
    auto result = perf_executor_->execute(topo);
    resp->set_src_oop(result.src_oop); resp->set_dst_iop(result.dst_iop);
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::BatchGetFiberPerformance(grpc::ServerContext*, const fiber::maint::BatchGetFiberPerformanceRequest* req, fiber::maint::BatchGetFiberPerformanceResponse* resp) {
    std::vector<int32_t> ids(req->fiber_ids().begin(), req->fiber_ids().end());
    auto topos = resolver_.resolve_batch(ids);
    auto results = perf_executor_->batch_execute(topos);
    std::unordered_map<int32_t, PerfResult> rm;
    for (auto& r : results) rm[r.fiber_id] = std::move(r);
    for (int32_t fid : ids) {
        auto* out = resp->add_results(); out->set_fiber_id(fid);
        auto it = rm.find(fid);
        if (it == rm.end()) { out->set_found(false); } else { out->set_found(true); out->set_src_oop(it->second.src_oop); out->set_dst_iop(it->second.dst_iop); }
    }
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberHistoryPerformance(grpc::ServerContext*, const fiber::maint::GetFiberHistoryPerformanceRequest* req, fiber::maint::GetFiberHistoryPerformanceResponse* resp) {
    auto topo = resolver_.resolve(req->fiber_id());
    if (topo.fiber_id == 0) return grpc::Status(grpc::NOT_FOUND, "Not found");
    if (!topo.is_inter_ne) return grpc::Status(grpc::FAILED_PRECONDITION, "Only inter-NE");
    int32_t sb = topo.src.board_id, db = topo.dst.board_id;
    if (topo.scene_type == SceneType::SCENE_2 && topo.primary_peer) db = topo.primary_peer->board_id;
    grpc::ClientContext c1; fiber::performance::GetHistoryPerformanceRequest h1; h1.set_board_id(sb); h1.set_port_id(1); h1.set_start_time(req->start_time()); h1.set_end_time(req->end_time());
    fiber::performance::GetHistoryPerformanceResponse r1; perf_stub_->GetHistoryPerformance(&c1, h1, &r1);
    grpc::ClientContext c2; fiber::performance::GetHistoryPerformanceRequest h2; h2.set_board_id(db); h2.set_port_id(1); h2.set_start_time(req->start_time()); h2.set_end_time(req->end_time());
    fiber::performance::GetHistoryPerformanceResponse r2; perf_stub_->GetHistoryPerformance(&c2, h2, &r2);
    std::map<std::string, fiber::maint::FiberPerformanceRecord> rm;
    for (const auto& rec : r1.records()) { rm[rec.recorded_at()].set_recorded_at(rec.recorded_at()); rm[rec.recorded_at()].set_src_oop(rec.oop_value()); }
    for (const auto& rec : r2.records()) { rm[rec.recorded_at()].set_recorded_at(rec.recorded_at()); rm[rec.recorded_at()].set_dst_iop(rec.iop_value()); }
    for (const auto& [ts, rec] : rm) *resp->add_records() = rec;
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::BatchGetFiberHistoryPerformance(grpc::ServerContext*, const fiber::maint::BatchGetFiberHistoryPerformanceRequest* req, fiber::maint::BatchGetFiberHistoryPerformanceResponse* resp) {
    for (int32_t fid : req->fiber_ids()) {
        auto* result = resp->add_results(); result->set_fiber_id(fid);
        auto topo = resolver_.resolve(fid);
        if (topo.fiber_id == 0) { result->set_error_code(1); continue; }
        if (!topo.is_inter_ne) { result->set_error_code(2); continue; }
        int32_t sb = topo.src.board_id, db = topo.dst.board_id;
        if (topo.scene_type == SceneType::SCENE_2 && topo.primary_peer) db = topo.primary_peer->board_id;
        grpc::ClientContext c1; fiber::performance::GetHistoryPerformanceRequest h1; h1.set_board_id(sb); h1.set_port_id(1); h1.set_start_time(req->start_time()); h1.set_end_time(req->end_time());
        fiber::performance::GetHistoryPerformanceResponse r1; perf_stub_->GetHistoryPerformance(&c1, h1, &r1);
        grpc::ClientContext c2; fiber::performance::GetHistoryPerformanceRequest h2; h2.set_board_id(db); h2.set_port_id(1); h2.set_start_time(req->start_time()); h2.set_end_time(req->end_time());
        fiber::performance::GetHistoryPerformanceResponse r2; perf_stub_->GetHistoryPerformance(&c2, h2, &r2);
        std::map<std::string, fiber::maint::FiberPerformanceRecord> rm;
        for (const auto& rec : r1.records()) { rm[rec.recorded_at()].set_recorded_at(rec.recorded_at()); rm[rec.recorded_at()].set_src_oop(rec.oop_value()); }
        for (const auto& rec : r2.records()) { rm[rec.recorded_at()].set_recorded_at(rec.recorded_at()); rm[rec.recorded_at()].set_dst_iop(rec.iop_value()); }
        for (const auto& [ts, rec] : rm) *result->add_records() = rec;
    }
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberSpanloss(grpc::ServerContext*, const fiber::maint::GetFiberSpanlossRequest* req, fiber::maint::GetFiberSpanlossResponse* resp) {
    resp->set_fiber_id(req->fiber_id());
    auto topo = resolver_.resolve(req->fiber_id());
    if (topo.fiber_id == 0) return grpc::Status(grpc::NOT_FOUND, "Not found");
    if (!topo.is_inter_ne) { resp->set_spanloss(0.0); return grpc::Status::OK; }
    auto result = spanloss_calc_->calculate(topo);
    resp->set_spanloss(result.spanloss);
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::BatchGetFiberSpanloss(grpc::ServerContext*, const fiber::maint::BatchGetFiberSpanlossRequest* req, fiber::maint::BatchGetFiberSpanlossResponse* resp) {
    for (int32_t fid : req->fiber_ids()) {
        auto* out = resp->add_results(); out->set_fiber_id(fid);
        auto topo = resolver_.resolve(fid);
        if (topo.fiber_id == 0) { out->set_found(false); out->set_spanloss(0.0); continue; }
        out->set_found(true);
        if (!topo.is_inter_ne) { out->set_spanloss(0.0); continue; }
        out->set_spanloss(spanloss_calc_->calculate(topo).spanloss);
    }
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetColoredFibers(grpc::ServerContext*, const fiber::maint::GetColoredFibersRequest* req, fiber::maint::GetColoredFibersResponse* resp) {
    std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
    for (const auto& [fid, ce] : color_by_fiber_) {
        if (ce.color != req->color()) continue;
        auto f_it = fiber_by_id_.find(fid); if (f_it == fiber_by_id_.end()) continue;
        auto* info = resp->add_fibers(); auto* fi = info->mutable_fiber();
        fi->set_fiber_id(f_it->second.fiber_id); fi->set_src_board_id(f_it->second.src_board_id);
        fi->set_src_port_id(f_it->second.src_port_id); fi->set_src_ne_id(f_it->second.src_ne_id);
        fi->set_dst_board_id(f_it->second.dst_board_id); fi->set_dst_port_id(f_it->second.dst_port_id);
        fi->set_dst_ne_id(f_it->second.dst_ne_id);
        info->set_color(static_cast<fiber::common::FiberColor>(ce.color));
    }
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetAllColoredFibers(grpc::ServerContext*, const fiber::maint::GetAllColoredFibersRequest*, fiber::maint::GetAllColoredFibersResponse* resp) {
    std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
    for (const auto& [fid, ce] : color_by_fiber_) {
        if (ce.color != static_cast<int8_t>(FiberColor::RED) && ce.color != static_cast<int8_t>(FiberColor::YELLOW)) continue;
        auto f_it = fiber_by_id_.find(fid); if (f_it == fiber_by_id_.end()) continue;
        auto* info = resp->add_fibers(); auto* fi = info->mutable_fiber();
        fi->set_fiber_id(f_it->second.fiber_id); fi->set_src_board_id(f_it->second.src_board_id);
        fi->set_src_port_id(f_it->second.src_port_id); fi->set_src_ne_id(f_it->second.src_ne_id);
        fi->set_dst_board_id(f_it->second.dst_board_id); fi->set_dst_port_id(f_it->second.dst_port_id);
        fi->set_dst_ne_id(f_it->second.dst_ne_id);
        info->set_color(static_cast<fiber::common::FiberColor>(ce.color));
        info->set_scene_type(ce.scene_type);
    }
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberStatsRealtime(grpc::ServerContext*, const fiber::maint::GetFiberStatsRealtimeRequest*, fiber::maint::GetFiberStatsRealtimeResponse* resp) {
    std::shared_lock<std::shared_mutex> lock(cache_rw_mutex_);
    int32_t r = 0, y = 0, g = 0;
    for (const auto& [fid, ce] : color_by_fiber_) {
        if (ce.color == static_cast<int8_t>(FiberColor::RED)) r++;
        else if (ce.color == static_cast<int8_t>(FiberColor::YELLOW)) y++;
        else if (ce.color == static_cast<int8_t>(FiberColor::GREEN)) g++;
    }
    Logger::instance().info("Fiber stats: red={}, yellow={}, green={}", r, y, g);
    resp->set_red_count(r); resp->set_yellow_count(y); resp->set_green_count(g);
    resp->set_total_fibers(static_cast<int32_t>(fiber_by_id_.size()));
    resp->set_active_alarms(static_cast<int32_t>(alarm_cache_.size()));
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::GetFiberStatsTrend(grpc::ServerContext*, const fiber::maint::GetFiberStatsTrendRequest* req, fiber::maint::GetFiberStatsTrendResponse* resp) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return grpc::Status(grpc::INTERNAL, "DB error");
    char sql[512]; snprintf(sql, sizeof(sql),
        "SELECT timestamp,red_count,yellow_count,total_colored FROM fiber_stats_trend WHERE timestamp BETWEEN '%s' AND '%s' ORDER BY timestamp",
        req->start_time().c_str(), req->end_time().c_str());
    if (mysql_query(conn.get(), sql) != 0) return grpc::Status(grpc::INTERNAL, "Query failed");
    MYSQL_RES* res = mysql_store_result(conn.get()); MYSQL_ROW row;
    while ((row = mysql_fetch_row(res)) != nullptr) {
        auto* p = resp->add_points(); p->set_timestamp(row[0]);
        p->set_red_count(std::stoi(row[1])); p->set_yellow_count(std::stoi(row[2])); p->set_total_colored(std::stoi(row[3]));
    }
    mysql_free_result(res);
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::SubscribeFiberColorEvents(grpc::ServerContext* ctx, const fiber::maint::SubscribeFiberColorEventsRequest*, grpc::ServerWriter<fiber::maint::FiberColorEvent>* writer) {
    { std::lock_guard<std::mutex> lock(writer_mutex_); color_event_writers_.push_back(writer); }
    while (running_ && !ctx->IsCancelled()) std::this_thread::sleep_for(std::chrono::seconds(1));
    { std::lock_guard<std::mutex> lock(writer_mutex_); color_event_writers_.erase(std::remove(color_event_writers_.begin(), color_event_writers_.end(), writer), color_event_writers_.end()); }
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::PullCallResultCallback(grpc::ServerContext*, const fiber::maint::PullCallResultCallbackRequest* req, fiber::maint::PullCallResultCallbackResponse* resp) {
    Logger::instance().info("PullCall callback: task_id={}, alarms={}", req->task_id(), req->alarms_size());
    { std::unique_lock<std::shared_mutex> lock(cache_rw_mutex_);
      for (const auto& a : req->alarms()) alarm_cache_[{a.board_id(), a.port_id(), static_cast<int8_t>(a.alarm_level())}] = {a.raised_at()}; }
    if (req->status() == "COMPLETED") event_queue_.push_full_sync_done();
    resp->set_success(true);
    return grpc::Status::OK;
}

grpc::Status FiberMaintServiceImpl::HealthCheck(grpc::ServerContext*, const fiber::maint::HealthCheckRequest*, fiber::common::HealthCheckResponse* resp) {
    resp->set_serving(true);
    auto s = sync_state_.load();
    resp->set_version(s == SyncState::SYNCED ? "4.0-synced" : s == SyncState::STREAMING ? "4.0-streaming" : "4.0-starting");
    return grpc::Status::OK;
}
