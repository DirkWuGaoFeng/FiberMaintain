#include "board_service_impl.h"
#include "topology.grpc.pb.h"
#include <grpcpp/create_channel.h>
#include <unordered_set>

BoardServiceImpl::BoardServiceImpl() : running_(true) {}

BoardServiceImpl::~BoardServiceImpl() {
    running_ = false;
    event_cv_.notify_all();
}

bool BoardServiceImpl::init() {
    Config& config = Config::instance();
    std::string host = config.get_string("db.host", "localhost");
    int port = config.get_int("db.port", 3306);
    std::string user = config.get_string("db.user", "root");
    std::string password = config.get_string("db.password", "");
    std::string database = config.get_string("db.database", "db_board");
    
    return DBConnectionPool::instance().init(host, port, user, password, database);
}

grpc::Status BoardServiceImpl::CreateBoard(grpc::ServerContext* context,
                                           const fiber::board::CreateBoardRequest* request,
                                           fiber::board::CreateBoardResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t board_type = request->board_type();
    int32_t ne_id = request->ne_id();
    
    char sql[512];
    sprintf(sql, "SELECT COUNT(*) FROM boards WHERE board_id = %d", board_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    mysql_free_result(res);
    
    if (row && std::stoi(row[0]) > 0) {
        response->set_success(false);
        response->set_message("Board already exists");
        return grpc::Status(grpc::ALREADY_EXISTS, "Board already exists");
    }
    
    int port_count = (board_type == fiber::common::BoardType::ACTIVE) ? 1 : 3;
    
    for (int i = 1; i <= port_count; ++i) {
        sprintf(sql, "INSERT INTO boards (board_id, board_type, ne_id, port_id, port_occupied) "
                     "VALUES (%d, %d, %d, %d, false)", board_id, board_type, ne_id, i);
        
        if (mysql_query(conn.get(), sql) != 0) {
            response->set_success(false);
            response->set_message(mysql_error(conn.get()));
            return grpc::Status(grpc::INTERNAL, "");
        }
    }
    
    response->set_success(true);
    response->set_message("Board created");
    
    fiber::board::BoardEvent event;
    event.set_event_type(fiber::common::BoardEventType::BOARD_CREATED);
    event.set_board_id(board_id);
    event.set_board_type(static_cast<fiber::common::BoardType>(board_type));
    event.set_ne_id(ne_id);
    event.set_timestamp(get_current_timestamp());
    push_board_event(event);
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::DeleteBoard(grpc::ServerContext* context,
                                           const fiber::board::DeleteBoardRequest* request,
                                           fiber::board::DeleteBoardResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        response->set_message("Database connection failed");
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    
    char sql[256];
    sprintf(sql, "SELECT COUNT(*) FROM boards WHERE board_id = %d", board_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    mysql_free_result(res);
    
    if (!row || std::stoi(row[0]) == 0) {
        response->set_success(false);
        response->set_message("Board not found");
        return grpc::Status(grpc::NOT_FOUND, "Board not found");
    }
    
    std::string topology_addr = Config::instance().get_string("topology_service.addr", "localhost:50052");
    auto channel = grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials());
    auto stub = fiber::topology::TopologyService::NewStub(channel);
    
    std::unordered_set<int32_t> fiber_ids;
    
    for (int i = 1; i <= 3; ++i) {
        fiber::topology::GetFibersByPortRequest get_fibers_req;
        get_fibers_req.set_board_id(board_id);
        get_fibers_req.set_port_id(i);
        fiber::topology::GetFibersByPortResponse get_fibers_resp;
        
        grpc::ClientContext ctx;
        auto status = stub->GetFibersByPort(&ctx, get_fibers_req, &get_fibers_resp);
        
        if (status.ok()) {
            for (const auto& fiber : get_fibers_resp.fibers()) {
                fiber_ids.insert(fiber.fiber_id());
            }
        }
    }
    
    for (int32_t fiber_id : fiber_ids) {
        fiber::topology::DeleteFiberRequest del_req;
        del_req.set_fiber_id(fiber_id);
        fiber::topology::DeleteFiberResponse del_resp;
        
        grpc::ClientContext ctx2;
        auto del_status = stub->DeleteFiber(&ctx2, del_req, &del_resp);
        
        if (del_status.ok() && del_resp.success()) {
            response->add_deleted_fiber_ids(fiber_id);
        }
    }
    
    sprintf(sql, "DELETE FROM boards WHERE board_id = %d", board_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        response->set_message(mysql_error(conn.get()));
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    response->set_success(true);
    response->set_message("Board deleted");
    
    fiber::board::BoardEvent event;
    event.set_event_type(fiber::common::BoardEventType::BOARD_DELETED);
    event.set_board_id(board_id);
    event.set_timestamp(get_current_timestamp());
    push_board_event(event);
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::GetBoard(grpc::ServerContext* context,
                                        const fiber::board::GetBoardRequest* request,
                                        fiber::board::GetBoardResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    
    char sql[256];
    sprintf(sql, "SELECT board_type, ne_id, port_id, port_occupied FROM boards WHERE board_id = %d ORDER BY port_id", board_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    if (!res) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    auto board = response->mutable_board();
    board->set_board_id(board_id);
    
    MYSQL_ROW row;
    bool found = false;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        found = true;
        board->set_board_type(static_cast<fiber::common::BoardType>(std::stoi(row[0])));
        board->set_ne_id(std::stoi(row[1]));
        
        auto port = board->add_ports();
        port->set_port_id(std::stoi(row[2]));
        port->set_occupied(row[3][0] == '1');
    }
    
    mysql_free_result(res);
    
    if (!found) {
        return grpc::Status(grpc::NOT_FOUND, "Board not found");
    }
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::BatchGetBoards(grpc::ServerContext* context,
                                              const fiber::board::BatchGetBoardsRequest* request,
                                              fiber::board::BatchGetBoardsResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    for (int32_t board_id : request->board_ids()) {
        auto result = response->add_results();
        result->set_found(false);
        
        char sql[256];
        sprintf(sql, "SELECT board_type, ne_id, port_id, port_occupied FROM boards WHERE board_id = %d ORDER BY port_id", board_id);
        
        if (mysql_query(conn.get(), sql) != 0) {
            result->set_error_message(mysql_error(conn.get()));
            continue;
        }
        
        MYSQL_RES* res = mysql_store_result(conn.get());
        if (!res) {
            result->set_error_message("Query failed");
            continue;
        }
        
        MYSQL_ROW row;
        bool found = false;
        
        while ((row = mysql_fetch_row(res)) != nullptr) {
            found = true;
            auto board = result->mutable_board();
            board->set_board_id(board_id);
            board->set_board_type(static_cast<fiber::common::BoardType>(std::stoi(row[0])));
            board->set_ne_id(std::stoi(row[1]));
            
            auto port = board->add_ports();
            port->set_port_id(std::stoi(row[2]));
            port->set_occupied(row[3][0] == '1');
        }
        
        mysql_free_result(res);
        
        if (!found) {
            result->set_error_message("Board not found");
        } else {
            result->set_found(true);
        }
    }
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::ListBoards(grpc::ServerContext* context,
                                          const fiber::board::ListBoardsRequest* request,
                                          fiber::board::ListBoardsResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    char sql[256];
    sprintf(sql, "SELECT board_id, board_type, ne_id, port_id, port_occupied FROM boards ORDER BY board_id, port_id");
    
    if (mysql_query(conn.get(), sql) != 0) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_RES* res = mysql_store_result(conn.get());
    if (!res) {
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    MYSQL_ROW row;
    int32_t current_board_id = -1;
    fiber::common::BoardInfo* current_board = nullptr;
    
    while ((row = mysql_fetch_row(res)) != nullptr) {
        int32_t board_id = std::stoi(row[0]);
        int32_t board_type = std::stoi(row[1]);
        int32_t ne_id = std::stoi(row[2]);
        int32_t port_id = std::stoi(row[3]);
        
        if (board_id != current_board_id) {
            current_board = response->add_boards();
            current_board->set_board_id(board_id);
            current_board->set_board_type(static_cast<fiber::common::BoardType>(board_type));
            current_board->set_ne_id(ne_id);
            current_board_id = board_id;
        }
        
        auto port = current_board->add_ports();
        port->set_port_id(port_id);
        port->set_occupied(row[4][0] == '1');
    }
    
    mysql_free_result(res);
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::GetBoardFibers(grpc::ServerContext* context,
                                              const fiber::board::GetBoardFibersRequest* request,
                                              fiber::board::GetBoardFibersResponse* response) {
    std::string topology_addr = Config::instance().get_string("topology_service.addr", "localhost:50052");
    auto channel = grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials());
    auto stub = fiber::topology::TopologyService::NewStub(channel);
    
    fiber::topology::BatchGetFibersRequest batch_req;
    
    grpc::ClientContext ctx;
    fiber::topology::BatchGetFibersResponse batch_resp;
    
    auto status = stub->BatchGetFibers(&ctx, batch_req, &batch_resp);
    
    if (!status.ok()) {
        return grpc::Status(grpc::UNAVAILABLE, "Topology service unavailable");
    }
    
    int32_t board_id = request->board_id();
    
    for (const auto& result : batch_resp.results()) {
        if (!result.found()) continue;
        
        const auto& fiber = result.fiber();
        if (fiber.src_board_id() == board_id || fiber.dst_board_id() == board_id) {
            *response->add_fibers() = fiber;
        }
    }
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::SubscribeBoardEvents(grpc::ServerContext* context,
                                                    const fiber::board::SubscribeBoardEventsRequest* request,
                                                    grpc::ServerWriter<fiber::board::BoardEvent>* writer) {
    while (running_) {
        std::unique_lock<std::mutex> lock(event_mutex_);
        event_cv_.wait(lock, [this]() { return !event_queue_.empty() || !running_; });
        
        if (!running_) break;
        
        while (!event_queue_.empty()) {
            fiber::board::BoardEvent event = event_queue_.front();
            event_queue_.pop();
            lock.unlock();
            
            if (!writer->Write(event)) {
                Logger::instance().warn("Client disconnected from board event stream");
                return grpc::Status::OK;
            }
            
            lock.lock();
        }
    }
    
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::UpdatePortOccupied(grpc::ServerContext* context,
                                                  const fiber::board::UpdatePortOccupiedRequest* request,
                                                  fiber::board::UpdatePortOccupiedResponse* response) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) {
        response->set_success(false);
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    int32_t board_id = request->board_id();
    int32_t port_id = request->port_id();
    bool occupied = request->occupied();
    
    char sql[256];
    sprintf(sql, "UPDATE boards SET port_occupied = %s WHERE board_id = %d AND port_id = %d",
            occupied ? "true" : "false", board_id, port_id);
    
    if (mysql_query(conn.get(), sql) != 0) {
        response->set_success(false);
        return grpc::Status(grpc::INTERNAL, "");
    }
    
    response->set_success(true);
    return grpc::Status::OK;
}

grpc::Status BoardServiceImpl::HealthCheck(grpc::ServerContext* context,
                                           const fiber::board::HealthCheckRequest* request,
                                           fiber::common::HealthCheckResponse* response) {
    response->set_serving(true);
    response->set_version("1.0.0");
    return grpc::Status::OK;
}

void BoardServiceImpl::push_board_event(const fiber::board::BoardEvent& event) {
    std::lock_guard<std::mutex> lock(event_mutex_);
    event_queue_.push(event);
    event_cv_.notify_all();
}

bool BoardServiceImpl::validate_port_count(fiber::common::BoardType board_type, int32_t port_count) {
    if (board_type == fiber::common::BoardType::ACTIVE) {
        return port_count == 1;
    } else {
        return port_count == 3;
    }
}