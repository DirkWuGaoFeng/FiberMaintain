#pragma once

#include <grpcpp/grpcpp.h>
#include "alarm.grpc.pb.h"
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "common/common.h"
#include <string>
#include <memory>
#include <thread>
#include <atomic>

class WebSocketServer {
public:
    WebSocketServer();
    ~WebSocketServer();
    
    bool init(int port);
    void start();
    
private:
    void subscribe_alarm_events();
    void subscribe_board_events();
    void subscribe_fiber_events();
    
    int port_;
    std::atomic<bool> running_;
    
    std::shared_ptr<fiber::alarm::AlarmService::Stub> alarm_stub_;
    std::shared_ptr<fiber::board::BoardService::Stub> board_stub_;
    std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub_;
    
    std::thread alarm_sub_thread_;
    std::thread board_sub_thread_;
    std::thread fiber_sub_thread_;
};