#include <grpcpp/grpcpp.h>
#include <random>
#include <chrono>
#include <thread>
#include <iostream>
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "common.grpc.pb.h"

using namespace fiber::board;
using namespace fiber::topology;
using namespace fiber::common;

int main(int argc, char** argv) {
    std::string board_service_addr = "localhost:50051";
    std::string topology_service_addr = "localhost:50052";
    
    if (argc > 1) {
        board_service_addr = argv[1];
    }
    if (argc > 2) {
        topology_service_addr = argv[2];
    }
    
    std::cout << "=== 场景模拟器 ===" << std::endl;
    std::cout << "BoardService: " << board_service_addr << std::endl;
    std::cout << "TopologyService: " << topology_service_addr << std::endl;
    std::cout << std::endl;
    
    auto board_channel = grpc::CreateChannel(board_service_addr, grpc::InsecureChannelCredentials());
    auto board_stub = BoardService::NewStub(board_channel);
    
    auto topology_channel = grpc::CreateChannel(topology_service_addr, grpc::InsecureChannelCredentials());
    auto topology_stub = TopologyService::NewStub(topology_channel);
    
    std::cout << "--- 创建100个场景1 (有源盘→无源盘，单跳) ---" << std::endl;
    
    int scene1_count = 0;
    for (int i = 1; i <= 100; ++i) {
        int32_t active_board_id = 10000 + i;
        int32_t passive_board_id = 20000 + i;
        int32_t ne_id_a = 100 + (i / 10);
        int32_t ne_id_b = 200 + (i / 10);
        
        grpc::ClientContext ctx1;
        CreateBoardRequest board_req;
        board_req.set_board_id(active_board_id);
        board_req.set_board_type(BoardType::ACTIVE);
        board_req.set_ne_id(ne_id_a);
        CreateBoardResponse board_resp;
        
        auto status = board_stub->CreateBoard(&ctx1, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景1-" << i << ": 创建有源盘失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx2;
        board_req.set_board_id(passive_board_id);
        board_req.set_board_type(BoardType::PASSIVE);
        board_req.set_ne_id(ne_id_b);
        status = board_stub->CreateBoard(&ctx2, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景1-" << i << ": 创建无源盘失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx3;
        CreateFiberRequest fiber_req;
        fiber_req.set_src_board_id(active_board_id);
        fiber_req.set_src_port_id(1);
        fiber_req.set_dst_board_id(passive_board_id);
        fiber_req.set_dst_port_id(1);
        CreateFiberResponse fiber_resp;
        
        status = topology_stub->CreateFiber(&ctx3, fiber_req, &fiber_resp);
        if (status.ok() && fiber_resp.success()) {
            scene1_count++;
            if (i % 10 == 0) {
                std::cout << "[INFO] 场景1-" << i << ": 有源盘(" << active_board_id << ") → 无源盘(" << passive_board_id << ") [OK] fiber_id=" << fiber_resp.fiber_id() << std::endl;
            }
        } else {
            std::cout << "[WARN] 场景1-" << i << ": 创建连纤失败: " << status.error_message() << std::endl;
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    
    std::cout << std::endl << "场景1创建完成: " << scene1_count << "/100" << std::endl;
    std::cout << std::endl;
    
    std::cout << "--- 创建100个场景2 (有源盘→无源盘→有源盘，两跳) ---" << std::endl;
    
    int scene2_count = 0;
    for (int i = 1; i <= 100; ++i) {
        int32_t active_board_a = 30000 + i;
        int32_t passive_board_c = 40000 + i;
        int32_t passive_board_d = 60000 + i;
        int32_t active_board_b = 50000 + i;
        int32_t active_board_a2 = 70000 + i;
        int32_t ne_id_a = 300 + (i / 10);
        int32_t ne_id_b = 400 + (i / 10);
        
        grpc::ClientContext ctx1;
        CreateBoardRequest board_req;
        board_req.set_board_id(active_board_a);
        board_req.set_board_type(BoardType::ACTIVE);
        board_req.set_ne_id(ne_id_a);
        CreateBoardResponse board_resp;
        
        auto status = board_stub->CreateBoard(&ctx1, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建有源盘A失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx2;
        board_req.set_board_id(passive_board_c);
        board_req.set_board_type(BoardType::PASSIVE);
        board_req.set_ne_id(ne_id_a);
        status = board_stub->CreateBoard(&ctx2, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建源无源盘C失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx3;
        board_req.set_board_id(passive_board_d);
        board_req.set_board_type(BoardType::PASSIVE);
        board_req.set_ne_id(ne_id_b);
        status = board_stub->CreateBoard(&ctx3, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建宿无源盘D失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx4;
        board_req.set_board_id(active_board_b);
        board_req.set_board_type(BoardType::ACTIVE);
        board_req.set_ne_id(ne_id_b);
        status = board_stub->CreateBoard(&ctx4, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建有源盘B失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx5;
        board_req.set_board_id(active_board_a2);
        board_req.set_board_type(BoardType::ACTIVE);
        board_req.set_ne_id(ne_id_b);
        status = board_stub->CreateBoard(&ctx5, board_req, &board_resp);
        if (!status.ok()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建同层次有源盘A2失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx6;
        CreateFiberRequest fiber_req;
        fiber_req.set_src_board_id(active_board_a);
        fiber_req.set_src_port_id(1);
        fiber_req.set_dst_board_id(passive_board_c);
        fiber_req.set_dst_port_id(2);
        CreateFiberResponse fiber_resp;
        
        status = topology_stub->CreateFiber(&ctx6, fiber_req, &fiber_resp);
        if (!status.ok() || !fiber_resp.success()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建网元内连纤(A→C.P2)失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx7;
        fiber_req.set_src_board_id(passive_board_c);
        fiber_req.set_src_port_id(1);
        fiber_req.set_dst_board_id(passive_board_d);
        fiber_req.set_dst_port_id(1);
        
        status = topology_stub->CreateFiber(&ctx7, fiber_req, &fiber_resp);
        if (!status.ok() || !fiber_resp.success()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建网元间连纤(C.P1→D.P1)失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx8;
        fiber_req.set_src_board_id(passive_board_d);
        fiber_req.set_src_port_id(2);
        fiber_req.set_dst_board_id(active_board_b);
        fiber_req.set_dst_port_id(1);
        
        status = topology_stub->CreateFiber(&ctx8, fiber_req, &fiber_resp);
        if (!status.ok() || !fiber_resp.success()) {
            std::cout << "[WARN] 场景2-" << i << ": 创建网元内连纤(D.P2→B)失败: " << status.error_message() << std::endl;
            continue;
        }
        
        grpc::ClientContext ctx9;
        fiber_req.set_src_board_id(passive_board_d);
        fiber_req.set_src_port_id(3);
        fiber_req.set_dst_board_id(active_board_a2);
        fiber_req.set_dst_port_id(1);
        
        status = topology_stub->CreateFiber(&ctx9, fiber_req, &fiber_resp);
        if (status.ok() && fiber_resp.success()) {
            scene2_count++;
            if (i % 10 == 0) {
                std::cout << "[INFO] 场景2-" << i << ": A(" << active_board_a << ")→C(" << passive_board_c << ")→D(" << passive_board_d << ")→B(" << active_board_b << ") [OK]" << std::endl;
            }
        } else {
            std::cout << "[WARN] 场景2-" << i << ": 创建网元内连纤(D.P3→A2)失败: " << status.error_message() << std::endl;
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
    
    std::cout << std::endl << "场景2创建完成: " << scene2_count << "/100" << std::endl;
    std::cout << std::endl;
    std::cout << "=== 模拟完成 ===" << std::endl;
    std::cout << "场景1: " << scene1_count << "个" << std::endl;
    std::cout << "场景2: " << scene2_count << "个" << std::endl;
    std::cout << "总计: " << scene1_count + scene2_count << "个场景" << std::endl;
    
    return 0;
}