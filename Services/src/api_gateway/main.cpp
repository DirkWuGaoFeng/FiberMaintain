#include "http_server.h"
#include "websocket_server.h"

int main(int argc, char** argv) {
    std::string config_path = "config/api_gateway.conf";
    if (argc > 1) {
        config_path = argv[1];
    }
    
    if (!Config::instance().load(config_path)) {
        std::cerr << "Failed to load config: " << config_path << std::endl;
        return 1;
    }
    
    Logger::instance().set_level(LogLevel::DEBUG);
    
    int http_port = Config::instance().get_int("http.port", 8080);
    int ws_port = Config::instance().get_int("websocket.port", 8081);
    
    HttpServer http_server;
    if (!http_server.init(http_port)) {
        Logger::instance().error("Failed to initialize HTTP server");
        return 1;
    }
    
    WebSocketServer ws_server;
    if (!ws_server.init(ws_port)) {
        Logger::instance().error("Failed to initialize WebSocket server");
        return 1;
    }
    
    http_server.start();
    ws_server.start();
    
    while (true) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    
    return 0;
}