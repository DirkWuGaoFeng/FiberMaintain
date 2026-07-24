#include "topology_service_impl.h"
#include <grpcpp/server_builder.h>

int main(int argc, char** argv) {
    std::string config_path = "config/topology_service.conf";
    if (argc > 1) {
        config_path = argv[1];
    }
    
    if (!Config::instance().load(config_path)) {
        std::cerr << "Failed to load config: " << config_path << std::endl;
        return 1;
    }
    
    Logger::instance().set_level(LogLevel::DEBUG);
    
    TopologyServiceImpl service;
    if (!service.init()) {
        Logger::instance().error("Failed to initialize TopologyService");
        return 1;
    }
    
    std::string server_addr = Config::instance().get_string("server.addr", "0.0.0.0:50052");
    
    grpc::ServerBuilder builder;
    builder.AddListeningPort(server_addr, grpc::InsecureServerCredentials());
    builder.RegisterService(&service);
    
    std::unique_ptr<grpc::Server> server(builder.BuildAndStart());
    Logger::instance().info("TopologyService listening on: {}", server_addr);
    
    server->Wait();
    
    return 0;
}