#include "websocket_server.h"

WebSocketServer::WebSocketServer() : port_(8081), running_(true) {}

WebSocketServer::~WebSocketServer() {
    running_ = false;
    
    if (alarm_sub_thread_.joinable()) alarm_sub_thread_.join();
    if (board_sub_thread_.joinable()) board_sub_thread_.join();
    if (fiber_sub_thread_.joinable()) fiber_sub_thread_.join();
}

bool WebSocketServer::init(int port) {
    port_ = port;
    
    std::string alarm_addr = Config::instance().get_string("alarm_service.addr", "localhost:50054");
    std::string board_addr = Config::instance().get_string("board_service.addr", "localhost:50051");
    std::string topology_addr = Config::instance().get_string("topology_service.addr", "localhost:50062");
    
    alarm_stub_ = fiber::alarm::AlarmService::NewStub(grpc::CreateChannel(alarm_addr, grpc::InsecureChannelCredentials()));
    board_stub_ = fiber::board::BoardService::NewStub(grpc::CreateChannel(board_addr, grpc::InsecureChannelCredentials()));
    topology_stub_ = fiber::topology::TopologyService::NewStub(grpc::CreateChannel(topology_addr, grpc::InsecureChannelCredentials()));
    
    return true;
}

void WebSocketServer::start() {
    alarm_sub_thread_ = std::thread(&WebSocketServer::subscribe_alarm_events, this);
    board_sub_thread_ = std::thread(&WebSocketServer::subscribe_board_events, this);
    fiber_sub_thread_ = std::thread(&WebSocketServer::subscribe_fiber_events, this);
    
    Logger::instance().info("API Gateway WebSocket server listening on port: {}", port_);
}

void WebSocketServer::subscribe_alarm_events() {
    fiber::alarm::SubscribeAlarmEventsRequest req;
    grpc::ClientContext ctx;
    
    std::unique_ptr<grpc::ClientReader<fiber::alarm::AlarmEvent>> reader(alarm_stub_->SubscribeAlarmEvents(&ctx, req));
    
    fiber::alarm::AlarmEvent event;
    while (running_ && reader->Read(&event)) {
        Logger::instance().debug("Alarm event: type={}, board={}, port={}, level={}",
                                 event.event_type(), event.board_id(), event.port_id(), event.alarm_level());
    }
}

void WebSocketServer::subscribe_board_events() {
    fiber::board::SubscribeBoardEventsRequest req;
    grpc::ClientContext ctx;
    
    std::unique_ptr<grpc::ClientReader<fiber::board::BoardEvent>> reader(board_stub_->SubscribeBoardEvents(&ctx, req));
    
    fiber::board::BoardEvent event;
    while (running_ && reader->Read(&event)) {
        Logger::instance().debug("Board event: type={}, board={}", event.event_type(), event.board_id());
    }
}

void WebSocketServer::subscribe_fiber_events() {
    fiber::topology::SubscribeFiberEventsRequest req;
    grpc::ClientContext ctx;
    
    std::unique_ptr<grpc::ClientReader<fiber::topology::FiberEvent>> reader(topology_stub_->SubscribeFiberEvents(&ctx, req));
    
    fiber::topology::FiberEvent event;
    while (running_ && reader->Read(&event)) {
        Logger::instance().debug("Fiber event: type={}, fiber={}", event.event_type(), event.fiber_id());
    }
}