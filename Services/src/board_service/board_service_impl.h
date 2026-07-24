#pragma once

#include <grpcpp/grpcpp.h>
#include "board.grpc.pb.h"
#include "common/common.h"
#include <memory>
#include <mutex>
#include <condition_variable>
#include <queue>

class BoardServiceImpl : public fiber::board::BoardService::Service {
public:
    BoardServiceImpl();
    ~BoardServiceImpl();
    
    bool init();
    
    grpc::Status CreateBoard(grpc::ServerContext* context,
                             const fiber::board::CreateBoardRequest* request,
                             fiber::board::CreateBoardResponse* response) override;
    
    grpc::Status DeleteBoard(grpc::ServerContext* context,
                             const fiber::board::DeleteBoardRequest* request,
                             fiber::board::DeleteBoardResponse* response) override;
    
    grpc::Status GetBoard(grpc::ServerContext* context,
                          const fiber::board::GetBoardRequest* request,
                          fiber::board::GetBoardResponse* response) override;
    
    grpc::Status BatchGetBoards(grpc::ServerContext* context,
                                const fiber::board::BatchGetBoardsRequest* request,
                                fiber::board::BatchGetBoardsResponse* response) override;
    
    grpc::Status ListBoards(grpc::ServerContext* context,
                            const fiber::board::ListBoardsRequest* request,
                            fiber::board::ListBoardsResponse* response) override;
    
    grpc::Status GetBoardFibers(grpc::ServerContext* context,
                                const fiber::board::GetBoardFibersRequest* request,
                                fiber::board::GetBoardFibersResponse* response) override;
    
    grpc::Status SubscribeBoardEvents(grpc::ServerContext* context,
                                      const fiber::board::SubscribeBoardEventsRequest* request,
                                      grpc::ServerWriter<fiber::board::BoardEvent>* writer) override;
    
    grpc::Status UpdatePortOccupied(grpc::ServerContext* context,
                                    const fiber::board::UpdatePortOccupiedRequest* request,
                                    fiber::board::UpdatePortOccupiedResponse* response) override;
    
    grpc::Status HealthCheck(grpc::ServerContext* context,
                             const fiber::board::HealthCheckRequest* request,
                             fiber::common::HealthCheckResponse* response) override;
    
    void push_board_event(const fiber::board::BoardEvent& event);
    
private:
    std::mutex event_mutex_;
    std::condition_variable event_cv_;
    std::queue<fiber::board::BoardEvent> event_queue_;
    std::atomic<bool> running_;
    
    bool validate_port_count(fiber::common::BoardType board_type, int32_t port_count);
};