#include <grpcpp/grpcpp.h>
#include <random>
#include <chrono>
#include <thread>
#include <iostream>
#include <vector>
#include <map>
#include "board.grpc.pb.h"
#include "performance.grpc.pb.h"
#include "common.grpc.pb.h"

using namespace fiber::board;
using namespace fiber::performance;
using namespace fiber::common;

struct PortPerformance {
    int32_t board_id;
    int32_t port_id;
    double oop_base;
    double iop_base;
    double oop_current;
    double iop_current;
};

int main(int argc, char** argv) {
    std::string board_service_addr = "localhost:50051";
    std::string performance_service_addr = "localhost:50053";
    int report_interval_ms = 5000;
    
    if (argc > 1) {
        board_service_addr = argv[1];
    }
    if (argc > 2) {
        performance_service_addr = argv[2];
    }
    if (argc > 3) {
        report_interval_ms = std::stoi(argv[3]);
    }
    
    std::cout << "=== 性能模拟器 ===" << std::endl;
    std::cout << "BoardService: " << board_service_addr << std::endl;
    std::cout << "PerformanceService: " << performance_service_addr << std::endl;
    std::cout << "上报间隔: " << report_interval_ms << "ms" << std::endl;
    std::cout << std::endl;
    
    auto board_channel = grpc::CreateChannel(board_service_addr, grpc::InsecureChannelCredentials());
    auto board_stub = BoardService::NewStub(board_channel);
    
    auto perf_channel = grpc::CreateChannel(performance_service_addr, grpc::InsecureChannelCredentials());
    auto perf_stub = PerformanceService::NewStub(perf_channel);
    
    std::vector<PortPerformance> port_perfs;
    
    std::cout << "--- 获取所有单盘端口信息 ---" << std::endl;
    
    try {
        grpc::ClientContext ctx;
        ListBoardsRequest req;
        ListBoardsResponse resp;
        
        auto status = board_stub->ListBoards(&ctx, req, &resp);
        if (!status.ok()) {
            std::cerr << "[ERROR] 获取单盘列表失败: " << status.error_message() << std::endl;
            return 1;
        }
        
        std::random_device rd;
        std::mt19937 gen(rd());
        std::uniform_real_distribution<> oop_dist(-35.0, -5.0);
        std::uniform_real_distribution<> iop_dist(-40.0, -10.0);
        
        for (const auto& board : resp.boards()) {
            if (board.board_type() != 1) {
                continue;
            }
            for (const auto& port : board.ports()) {
                double oop_base = oop_dist(gen);
                double iop_base = iop_dist(gen);
                
                port_perfs.push_back({
                    board.board_id(),
                    port.port_id(),
                    oop_base,
                    iop_base,
                    oop_base,
                    iop_base
                });
            }
        }
        
        std::cout << "[INFO] 共获取 " << port_perfs.size() << " 个有源盘端口" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "[ERROR] 获取端口信息异常: " << e.what() << std::endl;
        return 1;
    }
    
    if (port_perfs.empty()) {
        std::cerr << "[ERROR] 没有可用的端口，无法模拟性能数据" << std::endl;
        return 1;
    }
    
    std::random_device rd;
    std::mt19937 gen(rd());
    std::normal_distribution<> noise_dist(0.0, 0.5);
    
    std::cout << std::endl << "--- 开始模拟性能数据 (按Ctrl+C停止) ---" << std::endl;
    
    int report_count = 0;
    
    while (true) {
        for (auto& perf : port_perfs) {
            double oop_noise = noise_dist(gen);
            double iop_noise = noise_dist(gen);
            
            perf.oop_current = perf.oop_base + oop_noise;
            perf.iop_current = perf.iop_base + iop_noise;
            
            perf.oop_current = std::max(-40.0, std::min(0.0, perf.oop_current));
            perf.iop_current = std::max(-45.0, std::min(-5.0, perf.iop_current));
            
            grpc::ClientContext ctx;
            ReportPerformanceRequest req;
            req.set_board_id(perf.board_id);
            req.set_port_id(perf.port_id);
            req.set_oop_value(perf.oop_current);
            req.set_iop_value(perf.iop_current);
            ReportPerformanceResponse resp;
            
            auto status = perf_stub->ReportPerformance(&ctx, req, &resp);
            if (!status.ok()) {
                std::cerr << "[WARN] 上报性能失败: board=" << perf.board_id << ", port=" << perf.port_id << ": " << status.error_message() << std::endl;
            }
        }
        
        report_count++;
        if (report_count % 10 == 0) {
            std::cout << "[INFO] 已上报 " << report_count << " 轮性能数据" << std::endl;
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(report_interval_ms));
    }
    
    return 0;
}