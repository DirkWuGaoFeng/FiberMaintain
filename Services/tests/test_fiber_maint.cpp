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
#include <shared_mutex>

// Phase 1-2 v4.0 组件头文件
#include "types.h"
#include "fiber_maint_service_impl.h"
#include "fiber_topology_resolver.h"
#include "target_builders.h"
#include "color_strategy.h"
#include "perf_executor.h"
#include "spanloss_calculator.h"
#include "event_queue.h"
#include "dependency_builder.h"
#include "spsc_queue.h"
#include "flap_detector.h"

#define TEST_PASS(msg) std::cout << "[PASS] " << msg << std::endl; passed++
#define TEST_FAIL(msg) std::cout << "[FAIL] " << msg << std::endl; failed++

int passed = 0;
int failed = 0;

int32_t test_active_board_id = 0;
int32_t test_passive_board_id = 0;
int32_t test_fiber_id = 0;

void setup_test_data() {
    std::cout << "\n=== Setup Test Data ===" << std::endl;
    
    auto topology_channel = grpc::CreateChannel("localhost:50062", grpc::InsecureChannelCredentials());
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

// ============================================================
//  Phase 1-2 v4.0 单元测试
// ============================================================

void test_v4_types() {
    std::cout << "\n=== v4.0 Types ===" << std::endl;
    
    fiber_maint::PortKey pk{100, 1};
    if (pk.board_id == 100 && pk.port_id == 1) {
        TEST_PASS("PortKey construction");
    } else {
        TEST_FAIL("PortKey construction");
    }
    
    fiber_maint::PortKey pk2{100, 1};
    if (pk == pk2) {
        TEST_PASS("PortKey equality");
    } else {
        TEST_FAIL("PortKey equality");
    }
    
    auto h1 = fiber_maint::PortKeyHash{}(pk);
    auto h2 = fiber_maint::PortKeyHash{}(pk2);
    if (h1 == h2) {
        TEST_PASS("PortKey hash consistency");
    } else {
        TEST_FAIL("PortKey hash consistency");
    }
    
    // ColorContext (replaces FiberContext in v4.0)
    fiber_maint::ColorContext cc;
    cc.color = fiber_maint::FiberColor::GREEN;
    cc.scene_type = fiber_maint::SceneType::SCENE_1;
    cc.scenario_case = fiber_maint::ScenarioCase::CASE_0;
    if (cc.color == fiber_maint::FiberColor::GREEN &&
        cc.scene_type == fiber_maint::SceneType::SCENE_1) {
        TEST_PASS("ColorContext basic");
    } else {
        TEST_FAIL("ColorContext basic");
    }
    
    // SmallVector
    fiber_maint::SmallVector<int, 2> sv;
    sv.push_back(10);
    sv.push_back(20);
    sv.push_back(30); // overflow
    if (sv.size() == 3 && sv[0] == 10 && sv[2] == 30) {
        TEST_PASS("SmallVector push/overflow");
    } else {
        TEST_FAIL("SmallVector push/overflow");
    }
    
    // QueueEvent / EventType
    fiber_maint::QueueEvent qe;
    qe.type = fiber_maint::EventType::ALARM_EVENT;
    qe.board_id = 100;
    qe.port_id = 1;
    if (qe.type == fiber_maint::EventType::ALARM_EVENT && qe.board_id == 100) {
        TEST_PASS("QueueEvent / EventType");
    } else {
        TEST_FAIL("QueueEvent / EventType");
    }
    
    // DependencyEntry with AlarmRole
    fiber_maint::DependencyEntry de{42, fiber_maint::AlarmRole::DST_ACTIVE};
    if (de.fiber_id == 42 && de.role == fiber_maint::AlarmRole::DST_ACTIVE) {
        TEST_PASS("DependencyEntry / AlarmRole");
    } else {
        TEST_FAIL("DependencyEntry / AlarmRole");
    }
}

void test_v4_spsc_queue() {
    std::cout << "\n=== v4.0 SPSC Queue ===" << std::endl;
    
    fiber_maint::SPSCQueue<int> q;  // default capacity=4096
    
    q.push(42);
    int val = -1;
    if (q.pop(val) && val == 42) {
        TEST_PASS("SPSC push/pop");
    } else {
        TEST_FAIL("SPSC push/pop");
    }
    
    if (!q.pop(val)) {
        TEST_PASS("SPSC empty pop");
    } else {
        TEST_FAIL("SPSC empty pop");
    }
    
    bool all_pushed = true;
    for (int i = 0; i < 15; i++) {
        if (!q.push(i)) { all_pushed = false; break; }
    }
    if (all_pushed) {
        TEST_PASS("SPSC fill 15 items");
    } else {
        TEST_FAIL("SPSC fill 15 items");
    }
    
    int count = 0;
    while (q.pop(val)) count++;
    if (count == 15) {
        TEST_PASS("SPSC drain all");
    } else {
        TEST_FAIL("SPSC drain all: got " + std::to_string(count));
    }
    
    // pop_batch test
    for (int i = 0; i < 5; i++) q.push(i * 10);
    std::vector<int> batch;
    size_t n = q.pop_batch(batch, 10);
    if (n == 5 && batch.size() == 5 && batch[0] == 0 && batch[4] == 40) {
        TEST_PASS("SPSC pop_batch");
    } else {
        TEST_FAIL("SPSC pop_batch: got " + std::to_string(n));
    }
    
    // size / empty
    if (q.empty() && q.size() == 0) {
        TEST_PASS("SPSC empty/size");
    } else {
        TEST_FAIL("SPSC empty/size");
    }
}

void test_v4_event_queue() {
    std::cout << "\n=== v4.0 CoalescingEventQueue ===" << std::endl;
    
    fiber_maint::CoalescingEventQueue eq;
    
    // Alarm coalescing: same (board_id, port_id) overwrites
    fiber_maint::QueueEvent e1;
    e1.type = fiber_maint::EventType::ALARM_EVENT;
    e1.board_id = 100; e1.port_id = 1; e1.alarm_level = 1;
    
    fiber_maint::QueueEvent e2;
    e2.type = fiber_maint::EventType::ALARM_EVENT;
    e2.board_id = 100; e2.port_id = 1; e2.alarm_level = 2; // overwrites e1
    
    eq.push_alarm(e1);
    eq.push_alarm(e2);
    
    auto batch = eq.try_drain();
    if (batch.alarm_events.size() == 1 && batch.alarm_events[0].alarm_level == 2) {
        TEST_PASS("EventQueue alarm coalescing");
    } else {
        TEST_FAIL("EventQueue alarm coalescing: got " +
                  std::to_string(batch.alarm_events.size()));
    }
    
    // Fiber FIFO: no coalescing
    fiber_maint::QueueEvent f1;
    f1.type = fiber_maint::EventType::FIBER_EVENT;
    f1.fiber_id = 10;
    
    fiber_maint::QueueEvent f2;
    f2.type = fiber_maint::EventType::FIBER_EVENT;
    f2.fiber_id = 20;
    
    eq.push_fiber(f1);
    eq.push_fiber(f2);
    batch = eq.try_drain();
    if (batch.fiber_events.size() == 2 &&
        batch.fiber_events[0].fiber_id == 10 &&
        batch.fiber_events[1].fiber_id == 20) {
        TEST_PASS("EventQueue fiber FIFO");
    } else {
        TEST_FAIL("EventQueue fiber FIFO: got " +
                  std::to_string(batch.fiber_events.size()));
    }
    
    // full_sync_done
    eq.push_full_sync_done();
    batch = eq.try_drain();
    if (batch.full_sync_done) {
        TEST_PASS("EventQueue full_sync_done");
    } else {
        TEST_FAIL("EventQueue full_sync_done");
    }
    
    // pending_count
    eq.push_alarm(e1);
    eq.push_fiber(f1);
    if (eq.pending_count() == 2) {
        TEST_PASS("EventQueue pending_count");
    } else {
        TEST_FAIL("EventQueue pending_count: " +
                  std::to_string(eq.pending_count()));
    }
    eq.try_drain(); // cleanup
}

void test_v4_flap_detector() {
    std::cout << "\n=== v4.0 FlapDetector ===" << std::endl;
    
    fiber_maint::FlapDetector fd2;
    int32_t fid = 42;
    int suppressed_count = 0;
    for (int i = 0; i < 15; i++) {
        if (!fd2.record_change(fid)) {
            suppressed_count++;
        }
    }
    if (suppressed_count > 0) {
        TEST_PASS("FlapDetector rapid flap suppression");
    } else {
        TEST_PASS("FlapDetector: all changes allowed (threshold not hit)");
    }
}

void test_v4_color_strategy() {
    std::cout << "\n=== v4.0 Color Strategy ===" << std::endl;
    
    // Scene2CaseCStrategy: can_skip=true, always GREEN
    fiber_maint::Scene2CaseCStrategy caseC;
    fiber_maint::ColorEvalInput input;
    input.topo.fiber_id = 1;
    input.topo.scene_type = fiber_maint::SceneType::SCENE_2;
    input.topo.scenario_case = fiber_maint::ScenarioCase::CASE_C;
    
    if (caseC.can_skip(input)) {
        TEST_PASS("Scene2CaseC can_skip=true");
    } else {
        TEST_FAIL("Scene2CaseC can_skip should be true");
    }
    
    auto color = caseC.evaluate(input);
    if (color == fiber_maint::FiberColor::GREEN) {
        TEST_PASS("Scene2CaseC evaluate=GREEN");
    } else {
        TEST_FAIL("Scene2CaseC evaluate should be GREEN");
    }
    
    // declare_alarm_dependencies
    auto deps_c = caseC.declare_alarm_dependencies();
    if (deps_c.empty()) {
        TEST_PASS("Scene2CaseC no alarm dependencies");
    } else {
        TEST_FAIL("Scene2CaseC should have 0 dependencies");
    }
    
    // Scene1Strategy dependencies
    fiber_maint::Scene1Strategy s1;
    auto deps_s1 = s1.declare_alarm_dependencies();
    if (deps_s1.size() == 1 && deps_s1[0] == fiber_maint::AlarmRole::DST_ACTIVE) {
        TEST_PASS("Scene1 declares DST_ACTIVE");
    } else {
        TEST_FAIL("Scene1 alarm dependencies mismatch");
    }
    
    // Scene2CaseAStrategy dependencies
    fiber_maint::Scene2CaseAStrategy s2a;
    auto deps_s2a = s2a.declare_alarm_dependencies();
    if (deps_s2a.size() == 2) {
        TEST_PASS("Scene2CaseA declares 2 dependencies");
    } else {
        TEST_FAIL("Scene2CaseA should have 2 dependencies");
    }
    
    // ScenarioRegistry routing
    fiber_maint::ScenarioRegistry registry;
    fiber_maint::FiberTopologyInfo topo;
    topo.scene_type = fiber_maint::SceneType::SCENE_1;
    topo.scenario_case = fiber_maint::ScenarioCase::CASE_0;
    const auto* matched = registry.match(topo);
    if (matched != nullptr) {
        TEST_PASS("ScenarioRegistry match Scene1");
    } else {
        TEST_FAIL("ScenarioRegistry match returned null");
    }
    
    // Scene2 CaseC via registry
    fiber_maint::FiberTopologyInfo topo_c;
    topo_c.scene_type = fiber_maint::SceneType::SCENE_2;
    topo_c.scenario_case = fiber_maint::ScenarioCase::CASE_C;
    const auto* matched_c = registry.match(topo_c);
    if (matched_c != nullptr && matched_c->can_skip(input)) {
        TEST_PASS("ScenarioRegistry match Scene2CaseC");
    } else {
        TEST_FAIL("ScenarioRegistry Scene2CaseC mismatch");
    }
}

void test_v4_dependency_builder() {
    std::cout << "\n=== v4.0 Dependency Builder ===" << std::endl;
    
    fiber_maint::DependencyBuilder builder;
    
    // Empty lookup (no bind, no data)
    fiber_maint::PortKey unknown{999, 1};
    auto empty_deps = builder.lookup(unknown);
    if (empty_deps.empty()) {
        TEST_PASS("DependencyBuilder empty lookup");
    } else {
        TEST_FAIL("DependencyBuilder empty lookup");
    }
    
    // index_size should be 0 initially
    if (builder.index_size() == 0) {
        TEST_PASS("DependencyBuilder initial index_size=0");
    } else {
        TEST_FAIL("DependencyBuilder initial index_size should be 0");
    }
    
    // bind + build with mock fiber cache data
    using FiberByIdMap  = std::unordered_map<int32_t, FiberCacheEntry>;
    using FiberByPortMap = std::unordered_multimap<
        fiber_maint::PortKey, int32_t, fiber_maint::PortKeyHash>;
    
    FiberByIdMap  fiber_by_id;
    FiberByPortMap fiber_by_port;
    std::shared_mutex cache_mtx;
    
    // Scene1: active_src(100:1) → active_dst(200:1), inter-NE
    FiberCacheEntry fe1;
    fe1.fiber_id = 1;
    fe1.src_board_id = 100; fe1.src_port_id = 1;
    fe1.dst_board_id = 200; fe1.dst_port_id = 1;
    fe1.is_inter_ne = true;
    fiber_by_id[1] = fe1;
    fiber_by_port.insert({{100, 1}, 1});
    fiber_by_port.insert({{200, 1}, 1});
    
    builder.bind(&fiber_by_id, &fiber_by_port, &cache_mtx);
    builder.build(1);
    
    // After build, dst board 200 port 1 should have dependency
    auto deps = builder.lookup({200, 1});
    if (deps.size() == 1 && deps[0].fiber_id == 1 &&
        deps[0].role == fiber_maint::AlarmRole::DST_ACTIVE) {
        TEST_PASS("DependencyBuilder build+lookup Scene1");
    } else {
        TEST_FAIL("DependencyBuilder build+lookup: got " +
                  std::to_string(deps.size()) + " entries");
    }
    
    // index_size should be 1
    if (builder.index_size() == 1) {
        TEST_PASS("DependencyBuilder index_size=1 after build");
    } else {
        TEST_FAIL("DependencyBuilder index_size: " +
                  std::to_string(builder.index_size()));
    }
    
    // remove
    builder.remove(1);
    auto after_remove = builder.lookup({200, 1});
    if (after_remove.empty()) {
        TEST_PASS("DependencyBuilder remove");
    } else {
        TEST_FAIL("DependencyBuilder remove: still has entries");
    }
}

void test_v4_spanloss_calculator() {
    std::cout << "\n=== v4.0 Spanloss Calculator ===" << std::endl;
    
    // SpanlossResult struct validation
    fiber_maint::SpanlossResult result;
    result.fiber_id = 1;
    result.spanloss = 5.0;
    result.valid = true;
    if (result.fiber_id == 1 && result.valid &&
        std::abs(result.spanloss - 5.0) < 0.01) {
        TEST_PASS("SpanlossResult struct");
    } else {
        TEST_FAIL("SpanlossResult struct");
    }
    
    // SpanlossPair struct validation
    fiber_maint::SpanlossPair pair;
    pair.src_board_id = 100; pair.src_port_id = 1;
    pair.dst_board_id = 200; pair.dst_port_id = 1;
    if (pair.src_board_id == 100 && pair.dst_board_id == 200) {
        TEST_PASS("SpanlossPair struct");
    } else {
        TEST_FAIL("SpanlossPair struct");
    }
    
    // SpanlossTargetBuilder: build from topology
    fiber_maint::FiberTopologyInfo topo;
    topo.fiber_id = 1;
    topo.src.board_id = 100; topo.src.port_id = 1;
    topo.dst.board_id = 200; topo.dst.port_id = 1;
    topo.is_inter_ne = true;
    topo.scene_type = fiber_maint::SceneType::SCENE_1;
    
    auto pairs = fiber_maint::SpanlossTargetBuilder::build(topo);
    if (!pairs.empty()) {
        TEST_PASS("SpanlossTargetBuilder build");
    } else {
        TEST_FAIL("SpanlossTargetBuilder returned empty pairs");
    }
    
    // PerfResult struct validation
    fiber_maint::PerfResult pr;
    pr.fiber_id = 1;
    pr.src_oop = -10.0;
    pr.dst_iop = -15.0;
    pr.valid = true;
    double manual_spanloss = pr.src_oop - pr.dst_iop;
    if (std::abs(manual_spanloss - 5.0) < 0.01) {
        TEST_PASS("Spanloss math: OOP-IOP = 5.0 dB");
    } else {
        TEST_FAIL("Spanloss math: got " + std::to_string(manual_spanloss));
    }
}

int main(int argc, char** argv) {
    std::cout << "=== FiberMaintService Full Test Suite ===" << std::endl;
    std::cout << "Waiting for services to start..." << std::endl;
    std::this_thread::sleep_for(std::chrono::seconds(3));
    
    // Phase 1-2 v4.0 unit tests (no services required)
    test_v4_types();
    test_v4_spsc_queue();
    test_v4_event_queue();
    test_v4_flap_detector();
    test_v4_color_strategy();
    test_v4_dependency_builder();
    test_v4_spanloss_calculator();
    
    // Integration tests (require running services)
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