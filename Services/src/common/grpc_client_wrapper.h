#pragma once

#include <grpcpp/grpcpp.h>
#include <memory>
#include <string>
#include <mutex>
#include <atomic>

template<typename ServiceStub>
class GrpcClientWrapper {
public:
    GrpcClientWrapper(const std::string& server_addr, int timeout_ms = 2000);
    ~GrpcClientWrapper();
    
    std::shared_ptr<ServiceStub> get_stub();
    void reconnect();
    
private:
    std::string server_addr_;
    int timeout_ms_;
    std::shared_ptr<grpc::Channel> channel_;
    std::shared_ptr<ServiceStub> stub_;
    std::mutex mutex_;
    std::atomic<bool> connected_;
};