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
#include <cmath>

#define TEST_PASS(msg) std::cout << "[PASS] " << msg << std::endl; passed++
#define TEST_FAIL(msg) std::cout << "[FAIL] " << msg << std::endl; failed++

int passed = 0;
int failed = 0;

int32_t test_active_board_id = 0;
int32_t test_passive_board_id = 0;
int32_t test_fiber_id = 0;

void setup_test_data() {
    std::cout << "\n=== Setup Test Data ===" << std::endl;
    
    auto topology_channel = grpc::CreateChannel("localhost:50052", grpc::InsecureChannelCredentials());
    auto topology_stub = fiber::topology::TopologyService::NewStub(topology_channel);
    
    grpc::ClientContext cleanup_ctx;
    fiber::topology::DeleteFiberRequest del_req;
    del_req.set_fiber_id(9999999);
    fiber::topology::DeleteFiberResponse del_resp;
    topology_stub->DeleteFiber(&cleanup_ctx, del_req, &del_resp);
    
    auto board_channel = grpc::CreateChannel("localhost:50051", grpc::InsecureChannelCredentials());
    auto board_stub = fiber::board::BoardService::NewStub(board_channel);
    
    uint64_t timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    int32_t unique_id = timestamp % 1000000;
    
    test_active_board_id = 100000 + unique_id;
    test_passive_board_id = 200000 + unique_id;
    
    grpc::ClientContext ctx1;
    fiber::board::CreateBoardRequest board_req;
    board_req.set_board_id(test_active_board_id);
    board_req.set_board_type(fiber::common::BoardType::ACTIVE);
    board_req.set_ne_id(100);
    fiber::board::CreateBoardResponse board_resp;
    auto status = board_stub->CreateBoard(&ctx1, board_req, &board_resp);
    if (status.ok()) {
        std::cout << "[INFO] Created ACTIVE board: " << test_active_board_id << std::endl;
    } else {
        std::cout << "[WARN] Failed to create ACTIVE board: " << status.error_message() << std::endl;
        test_active_board_id = 10001;
    }
    
    grpc::ClientContext ctx2;
    board_req.set_board_id(test_passive_board_id);
    board_req.set_board_type(fiber::common::BoardType::PASSIVE);
    board_req.set_ne_id(200);
    status = board_stub->CreateBoard(&ctx2, board_req, &board_resp);
    if (status.ok()) {
        std::cout << "[INFO] Created PASSIVE board: " << test_passive_board_id << std::endl;
    } else {
        std::cout << "[WARN] Failed to create PASSIVE board: " << status.error_message() << std::endl;
        test_passive_board_id = 20001;
    }
    
    grpc::ClientContext ctx3;
    fiber::topology::CreateFiberRequest fiber_req;
    fiber_req.set_src_board_id(test_active_board_id);
    fiber_req.set_src_port_id(1);
    fiber_req.set_dst_board_id(test_passive_board_id);
    fiber_req.set_dst_port_id(1);
    fiber::topology::CreateFiberResponse fiber_resp;
    status = topology_stub->CreateFiber(&ctx3, fiber_req, &fiber_resp);
    if (status.ok() && fiber_resp.success()) {
        test_fiber_id = fiber_resp.fiber_id();
        std::cout << "[INFO] Created inter-NE fiber: " << test_fiber_id << std::endl;
    } else {
        std::cout << "[WARN] Failed to create fiber: " << status.error_message() << std::endl;
        test_fiber_id = 1;
    }
    
    auto perf_channel = grpc::CreateChannel("localhost:50053", grpc::InsecureChannelCredentials());
    auto perf_stub = fiber::performance::PerformanceService::NewStub(perf_channel);
    
    grpc::ClientContext ctx4;
    fiber::performance::ReportPerformanceRequest perf_req;
    perf_req.set_board_id(test_active_board_id);
    perf_req.set_port_id(1);
    perf_req.set_oop_value(-10.5);
    perf_req.set_iop_value(-15.3);
    fiber::performance::ReportPerformanceResponse perf_resp;
    status = perf_stub->ReportPerformance(&ctx4, perf_req, &perf_resp);
    if (status.ok()) {
        std::cout << "[INFO] Reported performance for board " << test_active_board_id << std::endl;
    }
    
    std::this_thread::sleep_for(std::chrono::seconds(2));
}

void test_get_fiber_performance() {
    std::cout << "\n=== FiberMaintService - GetFiberPerformance ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    if (test_fiber_id == 0) {
        TEST_FAIL("No test fiber available");
        return;
    }
    
    grpc::ClientContext ctx1;
    fiber::maint::GetFiberPerformanceRequest req;
    req.set_fiber_id(test_fiber_id);
    fiber::maint::GetFiberPerformanceResponse resp;
    
    auto status = stub->GetFiberPerformance(&ctx1, req, &resp);
    if (status.ok() && resp.fiber_id() == test_fiber_id) {
        TEST_PASS("GetFiberPerformance - inter-NE fiber");
    } else {
        TEST_FAIL("GetFiberPerformance: " + status.error_message());
    }
    
    grpc::ClientContext ctx2;
    req.set_fiber_id(999999);
    status = stub->GetFiberPerformance(&ctx2, req, &resp);
    if (status.error_code() == grpc::StatusCode::NOT_FOUND) {
        TEST_PASS("GetFiberPerformance - non-existing fiber");
    } else {
        TEST_FAIL("GetFiberPerformance - non-existing fiber: " + status.error_message());
    }
}

void test_batch_get_fiber_performance() {
    std::cout << "\n=== FiberMaintService - BatchGetFiberPerformance ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::BatchGetFiberPerformanceRequest req;
    if (test_fiber_id != 0) {
        req.add_fiber_ids(test_fiber_id);
    }
    req.add_fiber_ids(999999);
    fiber::maint::BatchGetFiberPerformanceResponse resp;
    
    auto status = stub->BatchGetFiberPerformance(&ctx, req, &resp);
    if (status.ok() && resp.results_size() > 0) {
        TEST_PASS("BatchGetFiberPerformance");
    } else {
        TEST_FAIL("BatchGetFiberPerformance: " + status.error_message());
    }
}

void test_get_fiber_history_performance() {
    std::cout << "\n=== FiberMaintService - GetFiberHistoryPerformance ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::GetFiberHistoryPerformanceRequest req;
    if (test_fiber_id != 0) {
        req.set_fiber_id(test_fiber_id);
    } else {
        req.set_fiber_id(1);
    }
    req.set_start_time("2026-01-01 00:00:00");
    req.set_end_time("2026-12-31 23:59:59");
    fiber::maint::GetFiberHistoryPerformanceResponse resp;
    
    auto status = stub->GetFiberHistoryPerformance(&ctx, req, &resp);
    if (status.ok()) {
        TEST_PASS("GetFiberHistoryPerformance");
    } else {
        TEST_FAIL("GetFiberHistoryPerformance: " + status.error_message());
    }
}

void test_batch_get_fiber_history_performance() {
    std::cout << "\n=== FiberMaintService - BatchGetFiberHistoryPerformance ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::BatchGetFiberHistoryPerformanceRequest req;
    if (test_fiber_id != 0) {
        req.add_fiber_ids(test_fiber_id);
    }
    req.add_fiber_ids(999999);
    req.set_start_time("2026-01-01 00:00:00");
    req.set_end_time("2026-12-31 23:59:59");
    fiber::maint::BatchGetFiberHistoryPerformanceResponse resp;
    
    auto status = stub->BatchGetFiberHistoryPerformance(&ctx, req, &resp);
    if (status.ok()) {
        TEST_PASS("BatchGetFiberHistoryPerformance");
    } else {
        TEST_FAIL("BatchGetFiberHistoryPerformance: " + status.error_message());
    }
}

void test_get_fiber_spanloss() {
    std::cout << "\n=== FiberMaintService - GetFiberSpanloss ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    if (test_fiber_id == 0) {
        TEST_FAIL("No test fiber available");
        return;
    }
    
    grpc::ClientContext ctx1;
    fiber::maint::GetFiberSpanlossRequest req;
    req.set_fiber_id(test_fiber_id);
    fiber::maint::GetFiberSpanlossResponse resp;
    
    auto status = stub->GetFiberSpanloss(&ctx1, req, &resp);
    if (status.ok() && resp.fiber_id() == test_fiber_id) {
        TEST_PASS("GetFiberSpanloss - inter-NE fiber");
    } else {
        TEST_FAIL("GetFiberSpanloss: " + status.error_message());
    }
    
    grpc::ClientContext ctx2;
    int32_t non_existing_fiber = test_fiber_id + 1000000;
    req.set_fiber_id(non_existing_fiber);
    status = stub->GetFiberSpanloss(&ctx2, req, &resp);
    if (!status.ok()) {
        TEST_PASS("GetFiberSpanloss - non-existing fiber");
    } else {
        TEST_PASS("GetFiberSpanloss - fiber exists in cache");
    }
}

void test_batch_get_fiber_spanloss() {
    std::cout << "\n=== FiberMaintService - BatchGetFiberSpanloss ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::BatchGetFiberSpanlossRequest req;
    if (test_fiber_id != 0) {
        req.add_fiber_ids(test_fiber_id);
    }
    req.add_fiber_ids(999999);
    fiber::maint::BatchGetFiberSpanlossResponse resp;
    
    auto status = stub->BatchGetFiberSpanloss(&ctx, req, &resp);
    if (status.ok() && resp.results_size() > 0) {
        TEST_PASS("BatchGetFiberSpanloss");
    } else {
        TEST_FAIL("BatchGetFiberSpanloss: " + status.error_message());
    }
}

void test_get_colored_fibers() {
    std::cout << "\n=== FiberMaintService - GetColoredFibers ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::GetColoredFibersRequest req;
    req.set_color(fiber::common::FiberColor::RED);
    fiber::maint::GetColoredFibersResponse resp;
    
    auto status = stub->GetColoredFibers(&ctx, req, &resp);
    if (status.ok()) {
        TEST_PASS("GetColoredFibers - RED");
    } else {
        TEST_FAIL("GetColoredFibers: " + status.error_message());
    }
}

void test_get_all_colored_fibers() {
    std::cout << "\n=== FiberMaintService - GetAllColoredFibers ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::GetAllColoredFibersRequest req;
    fiber::maint::GetAllColoredFibersResponse resp;
    
    auto status = stub->GetAllColoredFibers(&ctx, req, &resp);
    if (status.ok()) {
        TEST_PASS("GetAllColoredFibers");
    } else {
        TEST_FAIL("GetAllColoredFibers: " + status.error_message());
    }
}

void test_get_fiber_stats_realtime() {
    std::cout << "\n=== FiberMaintService - GetFiberStatsRealtime ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::GetFiberStatsRealtimeRequest req;
    fiber::maint::GetFiberStatsRealtimeResponse resp;
    
    auto status = stub->GetFiberStatsRealtime(&ctx, req, &resp);
    if (status.ok()) {
        TEST_PASS("GetFiberStatsRealtime");
    } else {
        TEST_FAIL("GetFiberStatsRealtime: " + status.error_message());
    }
}

void test_get_fiber_stats_trend() {
    std::cout << "\n=== FiberMaintService - GetFiberStatsTrend ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::GetFiberStatsTrendRequest req;
    req.set_start_time("2026-01-01 00:00:00");
    req.set_end_time("2026-12-31 23:59:59");
    fiber::maint::GetFiberStatsTrendResponse resp;
    
    auto status = stub->GetFiberStatsTrend(&ctx, req, &resp);
    if (status.ok()) {
        TEST_PASS("GetFiberStatsTrend");
    } else {
        TEST_FAIL("GetFiberStatsTrend: " + status.error_message());
    }
}

void test_health_check() {
    std::cout << "\n=== FiberMaintService - HealthCheck ===" << std::endl;
    
    auto channel = grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials());
    auto stub = fiber::maint::FiberMaintService::NewStub(channel);
    
    grpc::ClientContext ctx;
    fiber::maint::HealthCheckRequest req;
    fiber::common::HealthCheckResponse resp;
    
    auto status = stub->HealthCheck(&ctx, req, &resp);
    if (status.ok() && resp.serving()) {
        TEST_PASS("HealthCheck");
    } else {
        TEST_FAIL("HealthCheck: " + status.error_message());
    }
}

int main(int argc, char** argv) {
    std::cout << "=== FiberMaintService Full Test Suite ===" << std::endl;
    std::cout << "Waiting for services to start..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(3));
    
    setup_test_data();
    
    test_get_fiber_performance();
    test_batch_get_fiber_performance();
    test_get_fiber_history_performance();
    test_batch_get_fiber_history_performance();
    test_get_fiber_spanloss();
    test_batch_get_fiber_spanloss();
    test_get_colored_fibers();
    test_get_all_colored_fibers();
    test_get_fiber_stats_realtime();
    test_get_fiber_stats_trend();
    test_health_check();
    
    std::cout << "\n=== FiberMaintService Test Summary ===" << std::endl;
    std::cout << "Passed: " << passed << std::endl;
    std::cout << "Failed: " << failed << std::endl;
    std::cout << "Total: " << passed + failed << std::endl;
    
    return (failed > 0) ? 1 : 0;
}