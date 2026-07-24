#include "grpc_client_wrapper.h"
#include "logger.h"

template<typename ServiceStub>
GrpcClientWrapper<ServiceStub>::GrpcClientWrapper(const std::string& server_addr, int timeout_ms)
    : server_addr_(server_addr), timeout_ms_(timeout_ms), connected_(false) {
    reconnect();
}

template<typename ServiceStub>
GrpcClientWrapper<ServiceStub>::~GrpcClientWrapper() {}

template<typename ServiceStub>
std::shared_ptr<ServiceStub> GrpcClientWrapper<ServiceStub>::get_stub() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!connected_) {
        reconnect();
    }
    return stub_;
}

template<typename ServiceStub>
void GrpcClientWrapper<ServiceStub>::reconnect() {
    std::lock_guard<std::mutex> lock(mutex_);
    
    grpc::ChannelArguments args;
    args.SetInt(GRPC_ARG_MAX_RECEIVE_MESSAGE_LENGTH, 1024 * 1024 * 100);
    args.SetInt(GRPC_ARG_MAX_SEND_MESSAGE_LENGTH, 1024 * 1024 * 100);
    
    channel_ = grpc::CreateCustomChannel(
        server_addr_,
        grpc::InsecureChannelCredentials(),
        args
    );
    
    stub_ = ServiceStub::NewStub(channel_);
    connected_ = true;
    
    Logger::instance().info("gRPC client connected to: {}", server_addr_);
}