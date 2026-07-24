#include "topology_service_impl.h"

TopologyServiceImpl::TopologyServiceImpl() : running_(true) {}

TopologyServiceImpl::~TopologyServiceImpl() {
    running_ = false;
    event_cv_.notify_all();
}

bool TopologyServiceImpl::init() {
    Config& config = Config::instance();
    std::string host = config.get_string("db.host", "localhost");
    int port = config.get_int("db.port", 3306);
    std::string user = config.get_string("db.user", "root");
    std::string password = config.get_string("db.password", "");
    std::string database = config.get_string("db.database", "db_topology");

    // 初始化场景解析插件
    scene_resolver_.set_board_service_addr(
        config.get_string("board_service.addr", "localhost:50051"));

    return DBConnectionPool::instance().init(host, port, user, password, database);
}

grpc::Status TopologyServiceImpl::CreateFiber(grpc::ServerContext* context,
                                              const fiber::topology::CreateFiberRequest* request,
                                              fiber::topology::CreateFiberResponse* response) {
    int32_t src_board_id = request->src_board_id();
    int32_t src_port_id = request->src_port_id();
    int32_t dst_board_id = request->dst_board_id();
    int32_t dst_port_id = request->dst_port_id();
    
    if (src_board_id == dst_board_id && src_port_id == dst_port_id) {
        response->set_success(false);
        response->set_message("Cannot connect a port to itself");
        return grpc::Status(grpc::INVALID_ARGUMENT, "Invalid port connection");
    }
    
    if (!validate_board_exists(src_board_id)) {
        response->set_success(false);
        response->set_message("Source board not found");
        return grpc::Status(grpc::NOT_FOUND, "Source board not found");
    }
    
    if (!validate_board_exists(dst_board_id)) {
        response->set_success(false);
        response->set_message("Destination board not found");
        return grpc::Status(grpc::NOT_FOUND, "Destination board not found");
    }
    
    if (!validate_port_available(src_board_id, src_port_id)) {
        response->set_success(false);
        response->set_message("Source port is already occupied");
        return grpc::Status(grpc::FAILED_PRECONDITION, "Port occupied");
    }
    
    if (!validate_port_available(dst_board_id, dst_port_id)) {
        response->set_success(false);
        response->set_message("Destination port is already occupied");
        return grpc::Status(grpc::FAILED_PRECONDITION, "Port occupied");
    }
    
    if ((src_port_id == 1 && !validate_passive_port_one(src_board_id)) || 
        (dst_port_id == 1 && !validate_passive_port_one(dst_board_id))) {
        response->set_success(false);
        response->set_message("Passive board Port-1 can only connect one fiber");
        return grpc::Status(grpc::FAILED_PRECONDITION, "Port-1 already has connection");
    }
    
    if (!validate_port_purpose(src_board_id, src_port_id, dst_board_id)) {
        response->set_success(false);
        response->set_message("Port purpose mismatch");
        return grpc::Status(grpc::FAILED_PRECONDITION, "Port purpose mismatch");
    }
    
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t src_ne_id = get_board_ne_id(src_board_id);
    int32_t dst_ne_id = get_board_ne_id(dst_board_id);
    
    char sql[512];
    sprintf(sql, "INSERT INTO fiber_connections (src_board_id, src_port_id, src_ne_id, "
                 "dst_board_id, dst_port_id, dst_ne_id) VALUES (%d, %d, %d, %d, %d, %d)",
            src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t fiber_id = mysql_insert_id(conn.get());
    
    update_port_occupied(src_board_id, src_port_id, true);
    update_port_occupied(dst_board_id, dst_port_id, true);
    
    response->set_success(true);
    response->set_fiber_id(fiber_id);
    response->set_message("Fiber created");
    
    fiber::topology::FiberEvent event;
    event.set_event_type(fiber::common::FiberEventType::FIBER_CREATED);
    event.set_fiber_id(fiber_id);
    event.set_timestamp(get_current_timestamp());
    push_fiber_event(event);
    
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::DeleteFiber(grpc::ServerContext* context,
                                              const fiber::topology::DeleteFiberRequest* request,
                                              fiber::topology::DeleteFiberResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t fiber_id = request->fiber_id();
    
    char sql[256];
    sprintf(sql, "SELECT src_board_id, src_port_id, dst_board_id, dst_port_id FROM fiber_connections WHERE fiber_id = %d", fiber_id);
    
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
        response->set_message("Fiber not found");
        return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
    }
    
    int32_t src_board_id = std::stoi(row[0]);
    int32_t src_port_id = std::stoi(row[1]);
    int32_t dst_board_id = std::stoi(row[2]);
    int32_t dst_port_id = std::stoi(row[3]);
    
    mysql_free_result(res);
    
    sprintf(sql, "DELETE FROM fiber_connections WHERE fiber_id = %d", fiber_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    update_port_occupied(src_board_id, src_port_id, false);
    update_port_occupied(dst_board_id, dst_port_id, false);
    
    response->set_success(true);
    response->set_message("Fiber deleted");
    
    fiber::topology::FiberEvent event;
    event.set_event_type(fiber::common::FiberEventType::FIBER_DELETED);
    event.set_fiber_id(fiber_id);
    event.set_timestamp(get_current_timestamp());
    push_fiber_event(event);
    
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::GetFiber(grpc::ServerContext* context,
                                           const fiber::topology::GetFiberRequest* request,
                                           fiber::topology::GetFiberResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t fiber_id = request->fiber_id();
    
    char sql[256];
    sprintf(sql, "SELECT src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id, created_at "
                 "FROM fiber_connections WHERE fiber_id = %d", fiber_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    
    if (!row) {
        mysql_free_result(res);
        return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
    }
    
    auto fiber = response->mutable_fiber();
    fiber->set_fiber_id(fiber_id);
    fiber->set_src_board_id(std::stoi(row[0]));
    fiber->set_src_port_id(std::stoi(row[1]));
    fiber->set_src_ne_id(std::stoi(row[2]));
    fiber->set_dst_board_id(std::stoi(row[3]));
    fiber->set_dst_port_id(std::stoi(row[4]));
    fiber->set_dst_ne_id(std::stoi(row[5]));
    fiber->set_created_at(row[6]);
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::BatchGetFibers(grpc::ServerContext* context,
                                                 const fiber::topology::BatchGetFibersRequest* request,
                                                 fiber::topology::BatchGetFibersResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    if (request->fiber_ids().empty()) {
        char sql[512];
        sprintf(sql, "SELECT fiber_id, src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id, created_at "
                     "FROM fiber_connections");
        
        if (mysql_query(conn.get(), sql) != 0) {
            return grpc::Status(grpc::INTERNAL, "");
        }
        
        MYSQL_RES* res = mysql_store_result(conn.get());
        MYSQL_ROW row;
        
        while ((row = mysql_fetch_row(res)) != nullptr) {
            auto result = response->add_results();
            result->set_found(true);
            
            auto fiber = result->mutable_fiber();
            fiber->set_fiber_id(std::stoi(row[0]));
            fiber->set_src_board_id(std::stoi(row[1]));
            fiber->set_src_port_id(std::stoi(row[2]));
            fiber->set_src_ne_id(std::stoi(row[3]));
            fiber->set_dst_board_id(std::stoi(row[4]));
            fiber->set_dst_port_id(std::stoi(row[5]));
            fiber->set_dst_ne_id(std::stoi(row[6]));
            fiber->set_created_at(row[7]);
        }
        
        mysql_free_result(res);
        return grpc::Status::OK;
    }
    
    for (int32_t fiber_id : request->fiber_ids()) {
        auto result = response->add_results();
        result->set_found(false);
        
        char sql[256];
        sprintf(sql, "SELECT src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id, created_at "
                     "FROM fiber_connections WHERE fiber_id = %d", fiber_id);
        
        if (mysql_query(conn.get(), sql) != 0) {
            result->set_error_message(mysql_error(conn.get()));
            continue;
        }
        
        MYSQL_RES* res = mysql_store_result(conn.get());
        MYSQL_ROW row = mysql_fetch_row(res);
        
        if (!row) {
            mysql_free_result(res);
            result->set_error_message("Fiber not found");
            continue;
        }
        
        result->set_found(true);
        
        auto fiber = result->mutable_fiber();
        fiber->set_fiber_id(fiber_id);
        fiber->set_src_board_id(std::stoi(row[0]));
        fiber->set_src_port_id(std::stoi(row[1]));
        fiber->set_src_ne_id(std::stoi(row[2]));
        fiber->set_dst_board_id(std::stoi(row[3]));
        fiber->set_dst_port_id(std::stoi(row[4]));
        fiber->set_dst_ne_id(std::stoi(row[5]));
        fiber->set_created_at(row[6]);
        
        mysql_free_result(res);
    }
    
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::GetFibersByPort(grpc::ServerContext* context,
                                                  const fiber::topology::GetFibersByPortRequest* request,
                                                  fiber::topology::GetFibersByPortResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    
    char sql[512];
    sprintf(sql, "SELECT fiber_id, src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id, created_at "
                 "FROM fiber_connections WHERE (src_board_id = %d AND src_port_id = %d) OR (dst_board_id = %d AND dst_port_id = %d)",
            board_id, port_id, board_id, port_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        auto fiber = response->add_fibers();
        fiber->set_fiber_id(std::stoi(row[0]));
        fiber->set_src_board_id(std::stoi(row[1]));
        fiber->set_src_port_id(std::stoi(row[2]));
        fiber->set_src_ne_id(std::stoi(row[3]));
        fiber->set_dst_board_id(std::stoi(row[4]));
        fiber->set_dst_port_id(std::stoi(row[5]));
        fiber->set_dst_ne_id(std::stoi(row[6]));
        fiber->set_created_at(row[7]);
    }
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::SubscribeFiberEvents(grpc::ServerContext* context,
                                                       const fiber::topology::SubscribeFiberEventsRequest* request,
                                                       grpc::ServerWriter<fiber::topology::FiberEvent>* writer) {
    while (running_) {
        std::unique_lock<std::mutex> lock(event_mutex_);
        event_cv_.wait(lock, [this]() { return !event_queue_.empty() || !running_; });
        
        if (!running_) break;
        
        while (!event_queue_.empty()) {
            fiber::topology::FiberEvent event = event_queue_.front();
            event_queue_.pop();
            lock.unlock();
            
            if (!writer->Write(event)) {
                Logger::instance().warn("Client disconnected from fiber event stream");
                return grpc::Status::OK;
            }
            
            lock.lock();
        }
    }
    
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::GetFiberScene(grpc::ServerContext* context,
                                                const fiber::topology::GetFiberSceneRequest* request,
                                                fiber::topology::GetFiberSceneResponse* response) {
    int32_t fiber_id = request->inter_ne_fiber_id();

    // 使用场景解析插件
    auto scene = response->mutable_scene();
    if (!scene_resolver_.resolveScene(fiber_id, scene)) {
        response->set_found(false);
        response->set_error_message("Fiber not found or database error");
        return grpc::Status(grpc::NOT_FOUND, "Fiber not found");
    }

    response->set_found(true);
    return grpc::Status::OK;
}

grpc::Status TopologyServiceImpl::HealthCheck(grpc::ServerContext* context,
                                              const fiber::topology::HealthCheckRequest* request,
                                              fiber::common::HealthCheckResponse* response) {
    response->set_serving(true);
    response->set_version("1.0.0");
    return grpc::Status::OK;
}

void TopologyServiceImpl::push_fiber_event(const fiber::topology::FiberEvent& event) {
    std::lock_guard<std::mutex> lock(event_mutex_);
    event_queue_.push(event);
    event_cv_.notify_all();
}

bool TopologyServiceImpl::validate_board_exists(int32_t board_id) {
    std::string board_addr = Config::instance().get_string("board_service.addr", "localhost:50051");
    auto channel = grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials());
    auto stub = fiber::board::BoardService::NewStub(channel);
    
    fiber::board::GetBoardRequest req;
    req.set_board_id(board_id);
    fiber::board::GetBoardResponse resp;
    
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
    
    auto status = stub->GetBoard(&ctx, req, &resp);
    return status.ok();
}

bool TopologyServiceImpl::validate_port_available(int32_t board_id, int32_t port_id) {
    std::string board_addr = Config::instance().get_string("board_service.addr", "localhost:50051");
    auto channel = grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials());
    auto stub = fiber::board::BoardService::NewStub(channel);
    
    fiber::board::GetBoardRequest req;
    req.set_board_id(board_id);
    fiber::board::GetBoardResponse resp;
    
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
    
    auto status = stub->GetBoard(&ctx, req, &resp);
    if (!status.ok()) {
        return false;
    }
    
    for (const auto& port : resp.board().ports()) {
        if (port.port_id() == port_id) {
            return !port.occupied();
        }
    }
    
    return false;
}

bool TopologyServiceImpl::validate_port_purpose(int32_t board_id, int32_t port_id, int32_t dst_board_id) {
    return true;
}

bool TopologyServiceImpl::validate_passive_port_one(int32_t board_id) {
    fiber::common::BoardType board_type = scene_resolver_.getBoardType(board_id);
    if (board_type != fiber::common::BoardType::PASSIVE) {
        return true;
    }
    
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return true;
    }
    
    char sql[256];
    sprintf(sql, "SELECT COUNT(*) FROM fiber_connections WHERE (src_board_id = %d AND src_port_id = 1) OR (dst_board_id = %d AND dst_port_id = 1)",
            board_id, board_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        return true;
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    mysql_free_result(res);
    
    if (row && std::stoi(row[0]) > 0) {
        return false;
    }
    
    return true;
}

int32_t TopologyServiceImpl::get_board_ne_id(int32_t board_id) {
    std::string board_addr = Config::instance().get_string("board_service.addr", "localhost:50051");
    auto channel = grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials());
    auto stub = fiber::board::BoardService::NewStub(channel);
    
    fiber::board::GetBoardRequest req;
    req.set_board_id(board_id);
    fiber::board::GetBoardResponse resp;
    
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
    
    auto status = stub->GetBoard(&ctx, req, &resp);
    if (status.ok()) {
        return resp.board().ne_id();
    }
    
    return 0;
}

void TopologyServiceImpl::update_port_occupied(int32_t board_id, int32_t port_id, bool occupied) {
    std::string board_addr = Config::instance().get_string("board_service.addr", "localhost:50051");
    auto channel = grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials());
    auto stub = fiber::board::BoardService::NewStub(channel);
    
    fiber::board::UpdatePortOccupiedRequest req;
    req.set_board_id(board_id);
    req.set_port_id(port_id);
    req.set_occupied(occupied);
    fiber::board::UpdatePortOccupiedResponse resp;
    
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
    
    stub->UpdatePortOccupied(&ctx, req, &resp);
}