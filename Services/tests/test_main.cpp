#include <grpcpp/grpcpp.h>
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include "performance.grpc.pb.h"
#include "alarm.grpc.pb.h"
#include "fiber_maint.grpc.pb.h"
#include "common/common.h"
#include <iostream>
#include <chrono>
#include <thread>

#define TEST_PASS(msg) std::cout << "[PASS] " << msg << std::endl; passed++
#define TEST_FAIL(msg) std::cout << "[FAIL] " << msg << std::endl; failed++

int passed = 0;
int failed = 0;

void test_board_service() {
    std::cout << "\n=== BoardService Tests ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50051", grpc::InsecureChannelCredentials());
    auto stub = fiber::board::BoardService::NewStub(channel);
    
    fiber::board::CreateBoardRequest create_req;
    create_req.set_board_id(1001);
    create_req.set_board_type(fiber::common::BoardType::ACTIVE);
    create_req.set_ne_id(100);
    fiber::board::CreateBoardResponse create_resp;
    
    grpc::ClientContext ctx1;
    ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    auto status = stub->CreateBoard(&ctx1, create_req, &create_resp);
    if (status.ok() && create_resp.success()) {
        TEST_PASS("CreateBoard - ACTIVE board");
    } else {
        TEST_FAIL("CreateBoard - ACTIVE board: " + status.error_message());
    }
    
    create_req.set_board_id(2001);
    create_req.set_board_type(fiber::common::BoardType::PASSIVE);
    create_req.set_ne_id(200);
    grpc::ClientContext ctx2;
    ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->CreateBoard(&ctx2, create_req, &create_resp);
    if (status.ok() && create_resp.success()) {
        TEST_PASS("CreateBoard - PASSIVE board");
    } else {
        TEST_FAIL("CreateBoard - PASSIVE board: " + status.error_message());
    }
    
    fiber::board::GetBoardRequest get_req;
    get_req.set_board_id(1001);
    fiber::board::GetBoardResponse get_resp;
    
    grpc::ClientContext ctx3;
    ctx3.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->GetBoard(&ctx3, get_req, &get_resp);
    if (status.ok() && get_resp.board().board_id() == 1001) {
        TEST_PASS("GetBoard - existing board");
    } else {
        TEST_FAIL("GetBoard - existing board: " + status.error_message());
    }
    
    get_req.set_board_id(9999);
    grpc::ClientContext ctx4;
    ctx4.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->GetBoard(&ctx4, get_req, &get_resp);
    if (status.error_code() == grpc::StatusCode::NOT_FOUND) {
        TEST_PASS("GetBoard - non-existing board");
    } else {
        TEST_FAIL("GetBoard - non-existing board: " + status.error_message());
    }
}

void test_topology_service() {
    std::cout << "\n=== TopologyService Tests ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50062", grpc::InsecureChannelCredentials());
    auto stub = fiber::topology::TopologyService::NewStub(channel);
    
    fiber::topology::CreateFiberRequest create_req;
    create_req.set_src_board_id(1001);
    create_req.set_src_port_id(1);
    create_req.set_dst_board_id(2001);
    create_req.set_dst_port_id(1);
    fiber::topology::CreateFiberResponse create_resp;
    
    grpc::ClientContext ctx1;
    ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    auto status = stub->CreateFiber(&ctx1, create_req, &create_resp);
    if (status.ok() && create_resp.success()) {
        TEST_PASS("CreateFiber - inter-NE fiber");
    } else {
        TEST_FAIL("CreateFiber - inter-NE fiber: " + status.error_message());
    }
    
    fiber::topology::GetFiberRequest get_req;
    get_req.set_fiber_id(create_resp.fiber_id());
    fiber::topology::GetFiberResponse get_resp;
    
    grpc::ClientContext ctx2;
    ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->GetFiber(&ctx2, get_req, &get_resp);
    if (status.ok() && get_resp.fiber().fiber_id() == create_resp.fiber_id()) {
        TEST_PASS("GetFiber - existing fiber");
    } else {
        TEST_FAIL("GetFiber - existing fiber: " + status.error_message());
    }
    
    fiber::topology::DeleteFiberRequest del_req;
    del_req.set_fiber_id(create_resp.fiber_id());
    fiber::topology::DeleteFiberResponse del_resp;
    
    grpc::ClientContext ctx3;
    ctx3.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->DeleteFiber(&ctx3, del_req, &del_resp);
    if (status.ok() && del_resp.success()) {
        TEST_PASS("DeleteFiber");
    } else {
        TEST_FAIL("DeleteFiber: " + status.error_message());
    }
}

void test_performance_service() {
    std::cout << "\n=== PerformanceService Tests ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50053", grpc::InsecureChannelCredentials());
    auto stub = fiber::performance::PerformanceService::NewStub(channel);
    
    fiber::performance::ReportPerformanceRequest report_req;
    report_req.set_board_id(1001);
    report_req.set_port_id(1);
    report_req.set_oop_value(-10.5);
    report_req.set_iop_value(-15.3);
    fiber::performance::ReportPerformanceResponse report_resp;
    
    grpc::ClientContext ctx1;
    ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    auto status = stub->ReportPerformance(&ctx1, report_req, &report_resp);
    if (status.ok() && report_resp.success()) {
        TEST_PASS("ReportPerformance");
    } else {
        TEST_FAIL("ReportPerformance: " + status.error_message());
    }
    
    fiber::performance::GetCurrentPerformanceRequest get_req;
    get_req.set_board_id(1001);
    get_req.set_port_id(1);
    fiber::performance::GetCurrentPerformanceResponse get_resp;
    
    grpc::ClientContext ctx2;
    ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->GetCurrentPerformance(&ctx2, get_req, &get_resp);
    if (status.ok() && get_resp.board_id() == 1001) {
        TEST_PASS("GetCurrentPerformance");
    } else {
        TEST_FAIL("GetCurrentPerformance: " + status.error_message());
    }
}

void test_alarm_service() {
    std::cout << "\n=== AlarmService Tests ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50054", grpc::InsecureChannelCredentials());
    auto stub = fiber::alarm::AlarmService::NewStub(channel);
    
    fiber::alarm::ReportAlarmRequest report_req;
    report_req.set_board_id(1001);
    report_req.set_port_id(1);
    report_req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
    fiber::alarm::ReportAlarmResponse report_resp;
    
    grpc::ClientContext ctx1;
    ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    auto status = stub->ReportAlarm(&ctx1, report_req, &report_resp);
    if (status.ok() && report_resp.success()) {
        TEST_PASS("ReportAlarm - CRITICAL");
    } else {
        TEST_FAIL("ReportAlarm - CRITICAL: " + status.error_message());
    }
    
    fiber::alarm::GetCurrentAlarmRequest get_req;
    get_req.set_board_id(1001);
    get_req.set_port_id(1);
    fiber::alarm::GetCurrentAlarmResponse get_resp;
    
    grpc::ClientContext ctx2;
    ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->GetCurrentAlarm(&ctx2, get_req, &get_resp);
    if (status.ok() && get_resp.alarms_size() > 0) {
        TEST_PASS("GetCurrentAlarm");
    } else {
        TEST_FAIL("GetCurrentAlarm: " + status.error_message());
    }
    
    fiber::alarm::ClearAlarmRequest clear_req;
    clear_req.set_board_id(1001);
    clear_req.set_port_id(1);
    clear_req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
    fiber::alarm::ClearAlarmResponse clear_resp;
    
    grpc::ClientContext ctx3;
    ctx3.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->ClearAlarm(&ctx3, clear_req, &clear_resp);
    if (status.ok() && clear_resp.success()) {
        TEST_PASS("ClearAlarm");
    } else {
        TEST_FAIL("ClearAlarm: " + status.error_message());
    }
    
    fiber::alarm::CreatePullCallRequest pull_req;
    pull_req.set_include_history(false);
    pull_req.set_expire_seconds(60);
    fiber::alarm::CreatePullCallResponse pull_resp;
    
    grpc::ClientContext ctx4;
    ctx4.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->CreatePullCall(&ctx4, pull_req, &pull_resp);
    if (status.ok() && !pull_resp.task_id().empty()) {
        TEST_PASS("CreatePullCall");
    } else {
        TEST_FAIL("CreatePullCall: " + status.error_message());
    }
}

void test_fiber_maint_service() {
    std::cout << "\n=== FiberMaintService Tests ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    fiber::maint::GetFiberStatsRealtimeRequest stats_req;
    fiber::maint::GetFiberStatsRealtimeResponse stats_resp;
    
    grpc::ClientContext ctx1;
    ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    auto status = stub->GetFiberStatsRealtime(&ctx1, stats_req, &stats_resp);
    if (status.ok()) {
        TEST_PASS("GetFiberStatsRealtime");
    } else {
        TEST_FAIL("GetFiberStatsRealtime: " + status.error_message());
    }
    
    fiber::maint::HealthCheckRequest health_req;
    fiber::common::HealthCheckResponse health_resp;
    
    grpc::ClientContext ctx2;
    ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    status = stub->HealthCheck(&ctx2, health_req, &health_resp);
    if (status.ok() && health_resp.serving()) {
        TEST_PASS("HealthCheck");
    } else {
        TEST_FAIL("HealthCheck: " + status.error_message());
    }
}

void test_health_checks() {
    std::cout << "\n=== Health Check Tests ===" << std::endl;
    
    std::vector<std::string> services = {"localhost:50051", "localhost:50062", "localhost:50053", "localhost:50054", "localhost:50055"};
    std::vector<std::string> service_names = {"BoardService", "TopologyService", "PerformanceService", "AlarmService", "FiberMaintService"};
    
    for (size_t i = 0; i < services.size(); ++i) {
        auto channel = grpc::CreateChannel(services[i], grpc::InsecureChannelCredentials());
        
        fiber::common::HealthCheckResponse resp;
        grpc::Status status;
        
        if (i == 0) {
            auto stub = fiber::board::BoardService::NewStub(channel);
            fiber::board::HealthCheckRequest req;
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
            status = stub->HealthCheck(&ctx, req, &resp);
        } else if (i == 1) {
            auto stub = fiber::topology::TopologyService::NewStub(channel);
            fiber::topology::HealthCheckRequest req;
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
            status = stub->HealthCheck(&ctx, req, &resp);
        } else if (i == 2) {
            auto stub = fiber::performance::PerformanceService::NewStub(channel);
            fiber::performance::HealthCheckRequest req;
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
            status = stub->HealthCheck(&ctx, req, &resp);
        } else if (i == 3) {
            auto stub = fiber::alarm::AlarmService::NewStub(channel);
            fiber::alarm::HealthCheckRequest req;
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
            status = stub->HealthCheck(&ctx, req, &resp);
        } else {
            auto stub = fiber::maint::FiberMaintService::NewStub(channel);
            fiber::maint::HealthCheckRequest req;
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));
            status = stub->HealthCheck(&ctx, req, &resp);
        }
        
        if (status.ok() && resp.serving()) {
            TEST_PASS(service_names[i] + " health check");
        } else {
            TEST_FAIL(service_names[i] + " health check: " + status.error_message());
        }
    }
}

int main(int argc, char** argv) {
    std::cout << "=== Fiber Maintain Service System Test ===" << std::endl;
    std::cout << "Waiting for services to start..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(3));
    
    test_board_service();
    test_topology_service();
    test_performance_service();
    test_alarm_service();
    test_fiber_maint_service();
    test_health_checks();
    
    std::cout << "\n=== Test Summary ===" << std::endl;
    std::cout << "Passed: " << passed << std::endl;
    std::cout << "Failed: " << failed << std::endl;
    std::cout << "Total: " << passed + failed << std::endl;
    
    return (failed > 0) ? 1 : 0;
}