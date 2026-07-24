#pragma once

#include <grpcpp/grpcpp.h>
#include "topology.grpc.pb.h"
#include "board.grpc.pb.h"
#include "common/common.h"
#include "common/scene_resolver.h"
#include <memory>
#include <mutex>
#include <condition_variable>
#include <queue>

class TopologyServiceImpl : public fiber::topology::TopologyService::Service {
public:
    TopologyServiceImpl();
    ~TopologyServiceImpl();

    bool init();
    
    grpc::Status CreateFiber(grpc::ServerContext* context,
                             const fiber::topology::CreateFiberRequest* request,
                             fiber::topology::CreateFiberResponse* response) override;
    
    grpc::Status DeleteFiber(grpc::ServerContext* context,
                             const fiber::topology::DeleteFiberRequest* request,
                             fiber::topology::DeleteFiberResponse* response) override;
    
    grpc::Status GetFiber(grpc::ServerContext* context,
                          const fiber::topology::GetFiberRequest* request,
                          fiber::topology::GetFiberResponse* response) override;
    
    grpc::Status BatchGetFibers(grpc::ServerContext* context,
                                const fiber::topology::BatchGetFibersRequest* request,
                                fiber::topology::BatchGetFibersResponse* response) override;
    
    grpc::Status GetFibersByPort(grpc::ServerContext* context,
                                 const fiber::topology::GetFibersByPortRequest* request,
                                 fiber::topology::GetFibersByPortResponse* response) override;
    
    grpc::Status GetFiberScene(grpc::ServerContext* context,
                               const fiber::topology::GetFiberSceneRequest* request,
                               fiber::topology::GetFiberSceneResponse* response) override;
    
    grpc::Status SubscribeFiberEvents(grpc::ServerContext* context,
                                      const fiber::topology::SubscribeFiberEventsRequest* request,
                                      grpc::ServerWriter<fiber::topology::FiberEvent>* writer) override;
    
    grpc::Status HealthCheck(grpc::ServerContext* context,
                             const fiber::topology::HealthCheckRequest* request,
                             fiber::common::HealthCheckResponse* response) override;
    
    void push_fiber_event(const fiber::topology::FiberEvent& event);
    
private:
    std::mutex event_mutex_;
    std::condition_variable event_cv_;
    std::queue<fiber::topology::FiberEvent> event_queue_;
    std::atomic<bool> running_;
    
    bool validate_board_exists(int32_t board_id);
    bool validate_port_available(int32_t board_id, int32_t port_id);
    bool validate_port_purpose(int32_t board_id, int32_t port_id, int32_t dst_board_id);
    bool validate_passive_port_one(int32_t board_id);
    int32_t get_board_ne_id(int32_t board_id);

    void update_port_occupied(int32_t board_id, int32_t port_id, bool occupied);

    SceneResolver scene_resolver_;  // 场景解析插件
};