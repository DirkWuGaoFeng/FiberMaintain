#include <grpcpp/grpcpp.h>
#include <random>
#include <chrono>
#include <thread>
#include <iostream>
#include <map>
#include <vector>
#include <mutex>
#include "board.grpc.pb.h"
#include "alarm.grpc.pb.h"
#include "common.grpc.pb.h"

using namespace fiber::board;
using namespace fiber::alarm;
using namespace fiber::common;

struct ActiveAlarm {
    int32_t board_id;
    int32_t port_id;
    AlarmLevel level;
    std::chrono::time_point<std::chrono::steady_clock> raised_at;
    std::chrono::time_point<std::chrono::steady_clock> clear_at;
};

std::mutex alarm_mutex_;
std::vector<ActiveAlarm> active_alarms_;

int main(int argc, char** argv) {
    std::string board_service_addr = "localhost:50051";
    std::string alarm_service_addr = "localhost:50054";
    int report_interval_ms = 1000;
    
    if (argc > 1) {
        board_service_addr = argv[1];
    }
    if (argc > 2) {
        alarm_service_addr = argv[2];
    }
    if (argc > 3) {
        report_interval_ms = std::stoi(argv[3]);
    }
    
    std::cout << "=== 告警模拟器 ===" << std::endl;
    std::cout << "BoardService: " << board_service_addr << std::endl;
    std::cout << "AlarmService: " << alarm_service_addr << std::endl;
    std::cout << "上报间隔: " << report_interval_ms << "ms" << std::endl;
    std::cout << std::endl;
    
    auto board_channel = grpc::CreateChannel(board_service_addr, grpc::InsecureChannelCredentials());
    auto board_stub = BoardService::NewStub(board_channel);
    
    auto alarm_channel = grpc::CreateChannel(alarm_service_addr, grpc::InsecureChannelCredentials());
    auto alarm_stub = AlarmService::NewStub(alarm_channel);
    
    std::vector<std::pair<int32_t, int32_t>> ports;
    
    std::cout << "--- 获取所有有源盘端口信息 ---" << std::endl;
    
    try {
        grpc::ClientContext ctx;
        ListBoardsRequest req;
        ListBoardsResponse resp;
        
        auto status = board_stub->ListBoards(&ctx, req, &resp);
        if (!status.ok()) {
            std::cerr << "[ERROR] 获取单盘列表失败: " << status.error_message() << std::endl;
            return 1;
        }
        
        for (const auto& board : resp.boards()) {
            if (board.board_type() != 1) {
                continue;
            }
            for (const auto& port : board.ports()) {
                ports.emplace_back(board.board_id(), port.port_id());
            }
        }
        
        std::cout << "[INFO] 共获取 " << ports.size() << " 个有源盘端口" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "[ERROR] 获取端口信息异常: " << e.what() << std::endl;
        return 1;
    }
    
    if (ports.empty()) {
        std::cerr << "[ERROR] 没有可用的端口，无法模拟告警" << std::endl;
        return 1;
    }
    
    std::random_device rd;
    std::mt19937 gen(rd());
    std::uniform_int_distribution<> port_dist(0, ports.size() - 1);
    std::uniform_int_distribution<> level_dist(1, 2);
    std::uniform_int_distribution<> duration_dist(2000, 10000);
    
    std::cout << std::endl << "--- 开始模拟告警 (按Ctrl+C停止) ---" << std::endl;
    
    int alarm_count = 0;
    int clear_count = 0;
    
    while (true) {
        auto now = std::chrono::steady_clock::now();
        
        {
            std::lock_guard<std::mutex> lock(alarm_mutex_);
            for (auto it = active_alarms_.begin(); it != active_alarms_.end();) {
                if (now >= it->clear_at) {
                    grpc::ClientContext ctx;
                    ClearAlarmRequest req;
                    req.set_board_id(it->board_id);
                    req.set_port_id(it->port_id);
                    req.set_alarm_level(it->level);
                    ClearAlarmResponse resp;
                    
                    auto status = alarm_stub->ClearAlarm(&ctx, req, &resp);
                    if (status.ok() && resp.success()) {
                        clear_count++;
                        std::cout << "[INFO] 清除告警: board=" << it->board_id 
                                  << ", port=" << it->port_id 
                                  << ", level=" << (it->level == AlarmLevel::CRITICAL ? "CRITICAL" : "MINOR") 
                                  << ", 持续时间=" << std::chrono::duration_cast<std::chrono::seconds>(it->clear_at - it->raised_at).count() << "s" << std::endl;
                    }
                    
                    it = active_alarms_.erase(it);
                } else {
                    ++it;
                }
            }
        }
        
        if (std::rand() % 2 == 0) {
            auto [board_id, port_id] = ports[port_dist(gen)];
            AlarmLevel level = static_cast<AlarmLevel>(level_dist(gen));
            
            bool already_active = false;
            {
                std::lock_guard<std::mutex> lock(alarm_mutex_);
                for (const auto& alarm : active_alarms_) {
                    if (alarm.board_id == board_id && alarm.port_id == port_id && alarm.level == level) {
                        already_active = true;
                        break;
                    }
                }
            }
            
            if (!already_active) {
                grpc::ClientContext ctx;
                ReportAlarmRequest req;
                req.set_board_id(board_id);
                req.set_port_id(port_id);
                req.set_alarm_level(level);
                ReportAlarmResponse resp;
                
                auto status = alarm_stub->ReportAlarm(&ctx, req, &resp);
                if (status.ok() && resp.success()) {
                    alarm_count++;
                    
                    int duration_ms = duration_dist(gen);
                    auto raised_at = std::chrono::steady_clock::now();
                    auto clear_at = raised_at + std::chrono::milliseconds(duration_ms);
                    
                    {
                        std::lock_guard<std::mutex> lock(alarm_mutex_);
                        active_alarms_.push_back({board_id, port_id, level, raised_at, clear_at});
                    }
                    
                    std::cout << "[INFO] 产生告警: board=" << board_id 
                              << ", port=" << port_id 
                              << ", level=" << (level == AlarmLevel::CRITICAL ? "CRITICAL" : "MINOR") 
                              << ", 预计清除时间=" << duration_ms << "ms" << std::endl;
                }
            }
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(report_interval_ms));
    }
    
    return 0;
}