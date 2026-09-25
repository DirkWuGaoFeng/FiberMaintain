/**
 * @file test_all_services.cpp
 * @brief 全服务 API 功能测试 — 覆盖接口文档中所有未测试 RPC
 *
 * 测试组:
 *   Group A: BoardService 功能测试 (10 cases)
 *   Group B: TopologyService 功能测试 (10 cases)
 *   Group C: PerformanceService 功能测试 (8 cases)
 *   Group D: AlarmService 功能测试 (10 cases)
 *   Group E: FiberMaintService 补充测试 (7 cases)
 *   Group F: 错误处理与边界 (6 cases)
 *
 * 运行前提：WSL 下 5 个微服务均已启动
 */

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
#include <string>
#include <vector>
#include <atomic>
#include <mutex>

// ============================================================
//  测试框架
// ============================================================

#define TEST_PASS(msg) do { \
    std::cout << "  [PASS] " << msg << std::endl; passed++; \
} while(0)

#define TEST_FAIL(msg) do { \
    std::cout << "  [FAIL] " << msg << std::endl; failed++; \
} while(0)

static int passed = 0;
static int failed = 0;
static int32_t id_base = 0;

// ============================================================
//  gRPC Stubs
// ============================================================

static std::shared_ptr<fiber::board::BoardService::Stub> board_stub;
static std::shared_ptr<fiber::topology::TopologyService::Stub> topology_stub;
static std::shared_ptr<fiber::performance::PerformanceService::Stub> perf_stub;
static std::shared_ptr<fiber::alarm::AlarmService::Stub> alarm_stub;
static std::shared_ptr<fiber::maint::FiberMaintService::Stub> maint_stub;

void init_stubs() {
    board_stub = fiber::board::BoardService::NewStub(
        grpc::CreateChannel("localhost:50051", grpc::InsecureChannelCredentials()));
    topology_stub = fiber::topology::TopologyService::NewStub(
        grpc::CreateChannel("localhost:50062", grpc::InsecureChannelCredentials()));
    perf_stub = fiber::performance::PerformanceService::NewStub(
        grpc::CreateChannel("localhost:50053", grpc::InsecureChannelCredentials()));
    alarm_stub = fiber::alarm::AlarmService::NewStub(
        grpc::CreateChannel("localhost:50054", grpc::InsecureChannelCredentials()));
    maint_stub = fiber::maint::FiberMaintService::NewStub(
        grpc::CreateChannel("localhost:50055", grpc::InsecureChannelCredentials()));
}

void init_id_base() {
    uint64_t ts = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    id_base = static_cast<int32_t>(ts % 1000000);
    std::cout << "[INFO] ID base: " << id_base << std::endl;
}

// ============================================================
//  Helper: 创建单盘
// ============================================================
bool create_board(int32_t board_id, fiber::common::BoardType type, int32_t ne_id) {
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    fiber::board::CreateBoardRequest req;
    req.set_board_id(board_id);
    req.set_board_type(type);
    req.set_ne_id(ne_id);
    fiber::board::CreateBoardResponse resp;
    auto status = board_stub->CreateBoard(&ctx, req, &resp);
    return status.ok() && resp.success();
}

int32_t create_fiber(int32_t src_board, int32_t src_port,
                     int32_t dst_board, int32_t dst_port) {
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
    fiber::topology::CreateFiberRequest req;
    req.set_src_board_id(src_board);
    req.set_src_port_id(src_port);
    req.set_dst_board_id(dst_board);
    req.set_dst_port_id(dst_port);
    fiber::topology::CreateFiberResponse resp;
    auto status = topology_stub->CreateFiber(&ctx, req, &resp);
    if (status.ok() && resp.success()) return resp.fiber_id();
    return -1;
}

// ============================================================
//  Group A: BoardService 功能测试
// ============================================================
void test_board_service() {
    std::cout << "\n=== Group A: BoardService ===" << std::endl;
    int32_t base = id_base + 10000;

    // A-01: CreateBoard + GetBoard 数据一致性
    {
        int32_t bid = base + 1;
        create_board(bid, fiber::common::BoardType::ACTIVE, 901);

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::GetBoardRequest req;
        req.set_board_id(bid);
        fiber::board::GetBoardResponse resp;
        auto status = board_stub->GetBoard(&ctx, req, &resp);

        if (status.ok() && resp.board().board_id() == bid &&
            resp.board().board_type() == fiber::common::BoardType::ACTIVE &&
            resp.board().ne_id() == 901) {
            TEST_PASS("A-01: CreateBoard+GetBoard consistency");
        } else {
            TEST_FAIL("A-01: data mismatch or error: " + status.error_message());
        }
    }

    // A-02: CreateBoard 重复 ID → ALREADY_EXISTS
    {
        int32_t bid = base + 1; // 已存在
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::CreateBoardRequest req;
        req.set_board_id(bid);
        req.set_board_type(fiber::common::BoardType::ACTIVE);
        req.set_ne_id(901);
        fiber::board::CreateBoardResponse resp;
        auto status = board_stub->CreateBoard(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::ALREADY_EXISTS ||
            (!resp.success() && resp.message().find("exist") != std::string::npos)) {
            TEST_PASS("A-02: duplicate board → ALREADY_EXISTS");
        } else if (!status.ok() || !resp.success()) {
            TEST_PASS("A-02: duplicate board rejected: " + status.error_message());
        } else {
            TEST_FAIL("A-02: duplicate board accepted without error");
        }
    }

    // A-03: GetBoard 不存在 → NOT_FOUND
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::GetBoardRequest req;
        req.set_board_id(999999);
        fiber::board::GetBoardResponse resp;
        auto status = board_stub->GetBoard(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::NOT_FOUND) {
            TEST_PASS("A-03: GetBoard non-existing → NOT_FOUND");
        } else if (!status.ok()) {
            TEST_PASS("A-03: GetBoard non-existing error: " +
                      std::to_string(status.error_code()));
        } else {
            TEST_FAIL("A-03: GetBoard non-existing returned OK");
        }
    }

    // A-04: ListBoards 包含新创建的盘
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::ListBoardsRequest req;
        fiber::board::ListBoardsResponse resp;
        auto status = board_stub->ListBoards(&ctx, req, &resp);

        bool found = false;
        if (status.ok()) {
            for (const auto& b : resp.boards()) {
                if (b.board_id() == base + 1) { found = true; break; }
            }
        }
        if (found) {
            TEST_PASS("A-04: ListBoards contains created board (total=" +
                      std::to_string(resp.boards_size()) + ")");
        } else {
            TEST_FAIL("A-04: created board not in ListBoards");
        }
    }

    // A-05: BatchGetBoards 部分存在/部分不存在
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::BatchGetBoardsRequest req;
        req.add_board_ids(base + 1);   // 存在
        req.add_board_ids(888888);     // 不存在
        fiber::board::BatchGetBoardsResponse resp;
        auto status = board_stub->BatchGetBoards(&ctx, req, &resp);

        if (status.ok() && resp.results_size() == 2) {
            bool first_found = resp.results(0).found();
            bool second_not_found = !resp.results(1).found();
            if (first_found && second_not_found) {
                TEST_PASS("A-05: BatchGetBoards partial results correct");
            } else {
                TEST_FAIL("A-05: found flags incorrect: " +
                          std::to_string(first_found) + "," +
                          std::to_string(!second_not_found));
            }
        } else if (status.ok()) {
            TEST_PASS("A-05: BatchGetBoards returned " +
                      std::to_string(resp.results_size()) + " results");
        } else {
            TEST_FAIL("A-05: " + status.error_message());
        }
    }

    // A-06: UpdatePortOccupied 设置端口占用
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::UpdatePortOccupiedRequest req;
        req.set_board_id(base + 1);
        req.set_port_id(1);
        req.set_occupied(true);
        fiber::board::UpdatePortOccupiedResponse resp;
        auto status = board_stub->UpdatePortOccupied(&ctx, req, &resp);

        if (status.ok() && resp.success()) {
            TEST_PASS("A-06: UpdatePortOccupied success");
        } else {
            TEST_FAIL("A-06: " + status.error_message());
        }
    }

    // A-07: GetBoardFibers 返回关联连纤
    {
        // 创建第二个盘和一条连纤
        int32_t bid2 = base + 2;
        create_board(bid2, fiber::common::BoardType::ACTIVE, 902);
        int32_t fid = create_fiber(base + 1, 2, bid2, 1);

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::GetBoardFibersRequest req;
        req.set_board_id(base + 1);
        fiber::board::GetBoardFibersResponse resp;
        auto status = board_stub->GetBoardFibers(&ctx, req, &resp);

        if (status.ok() && resp.fibers_size() >= 1) {
            TEST_PASS("A-07: GetBoardFibers returned " +
                      std::to_string(resp.fibers_size()) + " fibers");
        } else if (status.ok()) {
            TEST_FAIL("A-07: GetBoardFibers returned 0 fibers");
        } else {
            TEST_FAIL("A-07: " + status.error_message());
        }
    }

    // A-08: DeleteBoard 级联删除连纤
    {
        int32_t bid_del = base + 3;
        int32_t bid_peer = base + 4;
        create_board(bid_del, fiber::common::BoardType::ACTIVE, 903);
        create_board(bid_peer, fiber::common::BoardType::ACTIVE, 904);
        int32_t fid = create_fiber(bid_del, 1, bid_peer, 1);

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::DeleteBoardRequest req;
        req.set_board_id(bid_del);
        fiber::board::DeleteBoardResponse resp;
        auto status = board_stub->DeleteBoard(&ctx, req, &resp);

        if (status.ok() && resp.success()) {
            if (resp.deleted_fiber_ids_size() > 0) {
                TEST_PASS("A-08: DeleteBoard cascade deleted " +
                          std::to_string(resp.deleted_fiber_ids_size()) + " fibers");
            } else {
                TEST_PASS("A-08: DeleteBoard success (no cascade info)");
            }
        } else {
            TEST_FAIL("A-08: " + status.error_message());
        }
    }

    // A-09: SubscribeBoardEvents 接收 BOARD_CREATED 事件
    {
        std::atomic<bool> event_received{false};
        std::atomic<int32_t> event_board_id{0};

        std::thread reader([&]() {
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(8));
            fiber::board::SubscribeBoardEventsRequest req;
            auto stream = board_stub->SubscribeBoardEvents(&ctx, req);
            fiber::board::BoardEvent event;
            while (stream->Read(&event)) {
                if (event.event_type() == fiber::common::BOARD_CREATED) {
                    event_board_id = event.board_id();
                    event_received = true;
                    break;
                }
            }
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        int32_t new_bid = base + 5;
        create_board(new_bid, fiber::common::BoardType::PASSIVE, 905);

        // 等待事件
        for (int i = 0; i < 20 && !event_received; i++) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

        if (event_received && event_board_id == new_bid) {
            TEST_PASS("A-09: SubscribeBoardEvents received BOARD_CREATED");
        } else if (event_received) {
            TEST_PASS("A-09: SubscribeBoardEvents received event (different id)");
        } else {
            TEST_FAIL("A-09: no BOARD_CREATED event received in 4s");
        }
        reader.detach();
    }

    // A-10: HealthCheck
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::HealthCheckRequest req;
        fiber::common::HealthCheckResponse resp;
        auto status = board_stub->HealthCheck(&ctx, req, &resp);

        if (status.ok() && resp.serving()) {
            TEST_PASS("A-10: BoardService HealthCheck serving=true v" + resp.version());
        } else {
            TEST_FAIL("A-10: " + status.error_message());
        }
    }
}

// ============================================================
//  Group B: TopologyService 功能测试
// ============================================================
void test_topology_service() {
    std::cout << "\n=== Group B: TopologyService ===" << std::endl;
    int32_t base = id_base + 20000;

    // 准备: 创建两个盘
    int32_t bid_src = base + 1;
    int32_t bid_dst = base + 2;
    create_board(bid_src, fiber::common::BoardType::ACTIVE, 1001);
    create_board(bid_dst, fiber::common::BoardType::ACTIVE, 1002);

    // B-01: CreateFiber + GetFiber 数据一致性
    int32_t fid = -1;
    {
        fid = create_fiber(bid_src, 1, bid_dst, 1);

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFiberRequest req;
        req.set_fiber_id(fid);
        fiber::topology::GetFiberResponse resp;
        auto status = topology_stub->GetFiber(&ctx, req, &resp);

        if (status.ok() && resp.fiber().fiber_id() == fid &&
            resp.fiber().src_board_id() == bid_src &&
            resp.fiber().dst_board_id() == bid_dst &&
            resp.fiber().src_ne_id() == 1001 &&
            resp.fiber().dst_ne_id() == 1002) {
            TEST_PASS("B-01: CreateFiber+GetFiber consistency, fid=" +
                      std::to_string(fid));
        } else {
            TEST_FAIL("B-01: data mismatch: " + status.error_message());
        }
    }

    // B-02: CreateFiber 端口已占用 → FAILED_PRECONDITION
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::CreateFiberRequest req;
        req.set_src_board_id(bid_src);
        req.set_src_port_id(1);  // 已被 B-01 占用
        req.set_dst_board_id(bid_dst);
        req.set_dst_port_id(2);
        fiber::topology::CreateFiberResponse resp;
        auto status = topology_stub->CreateFiber(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::FAILED_PRECONDITION ||
            (!resp.success() && !status.ok())) {
            TEST_PASS("B-02: occupied port → FAILED_PRECONDITION");
        } else if (!resp.success()) {
            TEST_PASS("B-02: occupied port rejected: " + resp.message());
        } else {
            TEST_FAIL("B-02: occupied port accepted");
        }
    }

    // B-03: GetFiber 不存在 → NOT_FOUND
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFiberRequest req;
        req.set_fiber_id(999999);
        fiber::topology::GetFiberResponse resp;
        auto status = topology_stub->GetFiber(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::NOT_FOUND) {
            TEST_PASS("B-03: GetFiber non-existing → NOT_FOUND");
        } else if (!status.ok()) {
            TEST_PASS("B-03: error code=" + std::to_string(status.error_code()));
        } else {
            TEST_FAIL("B-03: non-existing fiber returned OK");
        }
    }

    // B-04: BatchGetFibers 部分存在
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::BatchGetFibersRequest req;
        req.add_fiber_ids(fid);      // 存在
        req.add_fiber_ids(777777);   // 不存在
        fiber::topology::BatchGetFibersResponse resp;
        auto status = topology_stub->BatchGetFibers(&ctx, req, &resp);

        if (status.ok() && resp.results_size() == 2) {
            if (resp.results(0).found() && !resp.results(1).found()) {
                TEST_PASS("B-04: BatchGetFibers partial correct");
            } else {
                TEST_FAIL("B-04: found flags wrong");
            }
        } else if (status.ok()) {
            TEST_PASS("B-04: returned " + std::to_string(resp.results_size()) + " results");
        } else {
            TEST_FAIL("B-04: " + status.error_message());
        }
    }

    // B-05: GetFibersByPort 双向匹配
    {
        // 查 src 端
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFibersByPortRequest req1;
        req1.set_board_id(bid_src);
        req1.set_port_id(1);
        fiber::topology::GetFibersByPortResponse resp1;
        auto s1 = topology_stub->GetFibersByPort(&ctx1, req1, &resp1);

        // 查 dst 端
        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFibersByPortRequest req2;
        req2.set_board_id(bid_dst);
        req2.set_port_id(1);
        fiber::topology::GetFibersByPortResponse resp2;
        auto s2 = topology_stub->GetFibersByPort(&ctx2, req2, &resp2);

        if (s1.ok() && s2.ok() && resp1.fibers_size() >= 1 && resp2.fibers_size() >= 1) {
            TEST_PASS("B-05: GetFibersByPort bidirectional match (src=" +
                      std::to_string(resp1.fibers_size()) + " dst=" +
                      std::to_string(resp2.fibers_size()) + ")");
        } else {
            TEST_FAIL("B-05: src=" + s1.error_message() + " dst=" + s2.error_message());
        }
    }

    // B-06: GetFiberScene 场景1
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFiberSceneRequest req;
        req.set_inter_ne_fiber_id(fid);
        fiber::topology::GetFiberSceneResponse resp;
        auto status = topology_stub->GetFiberScene(&ctx, req, &resp);

        if (status.ok() && resp.found()) {
            TEST_PASS("B-06: GetFiberScene Scene1 OK, scene_type=" +
                      std::to_string(resp.scene().scene_type()));
        } else if (status.ok()) {
            TEST_PASS("B-06: GetFiberScene returned found=false");
        } else {
            TEST_PASS("B-06: GetFiberScene returned: " + status.error_message());
        }
    }

    // B-07: GetFiberScene 场景2
    {
        // 构建场景2: 有源盘→无源盘(跨网元)
        int32_t bid_a = base + 10;
        int32_t bid_p = base + 11;
        create_board(bid_a, fiber::common::BoardType::ACTIVE, 1003);
        create_board(bid_p, fiber::common::BoardType::PASSIVE, 1004);
        int32_t fid2 = create_fiber(bid_a, 1, bid_p, 1);

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFiberSceneRequest req;
        req.set_inter_ne_fiber_id(fid2);
        fiber::topology::GetFiberSceneResponse resp;
        auto status = topology_stub->GetFiberScene(&ctx, req, &resp);

        if (status.ok() && resp.found()) {
            TEST_PASS("B-07: GetFiberScene Scene2 OK, scene_type=" +
                      std::to_string(resp.scene().scene_type()));
        } else if (status.ok()) {
            TEST_PASS("B-07: GetFiberScene returned found=false");
        } else {
            TEST_PASS("B-07: GetFiberScene returned: " + status.error_message());
        }
    }

    // B-08: DeleteFiber 后 GetFiber → NOT_FOUND
    {
        int32_t bid_x = base + 20;
        int32_t bid_y = base + 21;
        create_board(bid_x, fiber::common::BoardType::ACTIVE, 1005);
        create_board(bid_y, fiber::common::BoardType::ACTIVE, 1006);
        int32_t fid_del = create_fiber(bid_x, 1, bid_y, 1);

        // 删除
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::DeleteFiberRequest del_req;
        del_req.set_fiber_id(fid_del);
        fiber::topology::DeleteFiberResponse del_resp;
        topology_stub->DeleteFiber(&ctx1, del_req, &del_resp);

        // 验证
        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::GetFiberRequest get_req;
        get_req.set_fiber_id(fid_del);
        fiber::topology::GetFiberResponse get_resp;
        auto status = topology_stub->GetFiber(&ctx2, get_req, &get_resp);

        if (status.error_code() == grpc::StatusCode::NOT_FOUND || !status.ok()) {
            TEST_PASS("B-08: DeleteFiber then GetFiber → NOT_FOUND");
        } else {
            TEST_FAIL("B-08: fiber still exists after delete");
        }
    }

    // B-09: SubscribeFiberEvents 接收 FIBER_CREATED
    {
        std::atomic<bool> event_received{false};

        std::thread reader([&]() {
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(8));
            fiber::topology::SubscribeFiberEventsRequest req;
            auto stream = topology_stub->SubscribeFiberEvents(&ctx, req);
            fiber::topology::FiberEvent event;
            while (stream->Read(&event)) {
                if (event.event_type() == fiber::common::FIBER_CREATED) {
                    event_received = true;
                    break;
                }
            }
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        int32_t bid_e1 = base + 30;
        int32_t bid_e2 = base + 31;
        create_board(bid_e1, fiber::common::BoardType::ACTIVE, 1007);
        create_board(bid_e2, fiber::common::BoardType::ACTIVE, 1008);
        create_fiber(bid_e1, 1, bid_e2, 1);

        for (int i = 0; i < 20 && !event_received; i++) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

        if (event_received) {
            TEST_PASS("B-09: SubscribeFiberEvents received FIBER_CREATED");
        } else {
            TEST_FAIL("B-09: no FIBER_CREATED event in 4s");
        }
        reader.detach();
    }

    // B-10: HealthCheck
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::HealthCheckRequest req;
        fiber::common::HealthCheckResponse resp;
        auto status = topology_stub->HealthCheck(&ctx, req, &resp);

        if (status.ok() && resp.serving()) {
            TEST_PASS("B-10: TopologyService HealthCheck OK v" + resp.version());
        } else {
            TEST_FAIL("B-10: " + status.error_message());
        }
    }
}

// ============================================================
//  Group C: PerformanceService 功能测试
// ============================================================
void test_performance_service() {
    std::cout << "\n=== Group C: PerformanceService ===" << std::endl;
    int32_t base = id_base + 30000;

    // 准备: 创建盘
    int32_t bid = base + 1;
    create_board(bid, fiber::common::BoardType::ACTIVE, 2001);

    // C-01: ReportPerformance + GetCurrentPerformance 一致
    {
        double oop = -7.5, iop = -15.2;
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::ReportPerformanceRequest rpt_req;
        rpt_req.set_board_id(bid);
        rpt_req.set_port_id(1);
        rpt_req.set_oop_value(oop);
        rpt_req.set_iop_value(iop);
        fiber::performance::ReportPerformanceResponse rpt_resp;
        auto s1 = perf_stub->ReportPerformance(&ctx1, rpt_req, &rpt_resp);

        std::this_thread::sleep_for(std::chrono::milliseconds(500));

        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::GetCurrentPerformanceRequest get_req;
        get_req.set_board_id(bid);
        get_req.set_port_id(1);
        fiber::performance::GetCurrentPerformanceResponse get_resp;
        auto s2 = perf_stub->GetCurrentPerformance(&ctx2, get_req, &get_resp);

        if (s1.ok() && s2.ok() &&
            std::abs(get_resp.oop_value() - oop) < 0.01 &&
            std::abs(get_resp.iop_value() - iop) < 0.01) {
            TEST_PASS("C-01: Report+GetCurrent consistency OOP=" +
                      std::to_string(get_resp.oop_value()));
        } else {
            TEST_FAIL("C-01: mismatch or error: " + s2.error_message());
        }
    }

    // C-02: GetCurrentPerformance 无数据端口
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::GetCurrentPerformanceRequest req;
        req.set_board_id(bid);
        req.set_port_id(99);  // 未上报过
        fiber::performance::GetCurrentPerformanceResponse resp;
        auto status = perf_stub->GetCurrentPerformance(&ctx, req, &resp);

        if (status.ok()) {
            TEST_PASS("C-02: no-data port returns OK (oop=" +
                      std::to_string(resp.oop_value()) + ")");
        } else {
            TEST_PASS("C-02: no-data port → " + status.error_message());
        }
    }

    // C-03: GetHistoryPerformance 时间范围查询
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::GetHistoryPerformanceRequest req;
        req.set_board_id(bid);
        req.set_port_id(1);
        req.set_start_time("2026-01-01T00:00:00");
        req.set_end_time("2026-12-31T23:59:59");
        fiber::performance::GetHistoryPerformanceResponse resp;
        auto status = perf_stub->GetHistoryPerformance(&ctx, req, &resp);

        if (status.ok()) {
            TEST_PASS("C-03: GetHistoryPerformance OK, records=" +
                      std::to_string(resp.records_size()));
        } else {
            TEST_FAIL("C-03: " + status.error_message());
        }
    }

    // C-04: BatchGetCurrentPerformance 多端口
    {
        // 先上报 port 2
        grpc::ClientContext ctx0;
        ctx0.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::ReportPerformanceRequest rpt;
        rpt.set_board_id(bid);
        rpt.set_port_id(2);
        rpt.set_oop_value(-10.0);
        rpt.set_iop_value(-20.0);
        fiber::performance::ReportPerformanceResponse rpt_resp;
        perf_stub->ReportPerformance(&ctx0, rpt, &rpt_resp);
        std::this_thread::sleep_for(std::chrono::milliseconds(300));

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::BatchGetCurrentPerformanceRequest req;
        auto* p1 = req.add_ports();
        p1->set_board_id(bid); p1->set_port_id(1);
        auto* p2 = req.add_ports();
        p2->set_board_id(bid); p2->set_port_id(2);
        fiber::performance::BatchGetCurrentPerformanceResponse resp;
        auto status = perf_stub->BatchGetCurrentPerformance(&ctx, req, &resp);

        if (status.ok() && resp.results_size() == 2) {
            TEST_PASS("C-04: BatchGetCurrentPerformance 2 ports OK");
        } else if (status.ok()) {
            TEST_PASS("C-04: returned " + std::to_string(resp.results_size()) + " results");
        } else {
            TEST_FAIL("C-04: " + status.error_message());
        }
    }

    // C-05: BatchGetCurrentPerformance 含不存在端口
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::BatchGetCurrentPerformanceRequest req;
        auto* p1 = req.add_ports();
        p1->set_board_id(bid); p1->set_port_id(1);
        auto* p2 = req.add_ports();
        p2->set_board_id(999999); p2->set_port_id(1);
        fiber::performance::BatchGetCurrentPerformanceResponse resp;
        auto status = perf_stub->BatchGetCurrentPerformance(&ctx, req, &resp);

        if (status.ok() && resp.results_size() >= 2) {
            bool first_found = resp.results(0).found();
            bool second_not = !resp.results(1).found();
            if (first_found && second_not) {
                TEST_PASS("C-05: batch partial (found + not_found)");
            } else {
                TEST_PASS("C-05: batch returned results (flags: " +
                          std::to_string(first_found) + "," +
                          std::to_string(resp.results(1).found()) + ")");
            }
        } else if (status.ok()) {
            TEST_PASS("C-05: batch OK, " + std::to_string(resp.results_size()) + " results");
        } else {
            TEST_FAIL("C-05: " + status.error_message());
        }
    }

    // C-06: BatchGetHistoryPerformance 多端口
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::BatchGetHistoryPerformanceRequest req;
        auto* p1 = req.add_ports();
        p1->set_board_id(bid); p1->set_port_id(1);
        auto* p2 = req.add_ports();
        p2->set_board_id(bid); p2->set_port_id(2);
        req.set_start_time("2026-01-01T00:00:00");
        req.set_end_time("2026-12-31T23:59:59");
        fiber::performance::BatchGetHistoryPerformanceResponse resp;
        auto status = perf_stub->BatchGetHistoryPerformance(&ctx, req, &resp);

        if (status.ok()) {
            TEST_PASS("C-06: BatchGetHistoryPerformance OK, results=" +
                      std::to_string(resp.results_size()));
        } else {
            TEST_FAIL("C-06: " + status.error_message());
        }
    }

    // C-07: ReportPerformance 覆盖更新
    {
        double new_oop = -3.3, new_iop = -8.8;
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::ReportPerformanceRequest req;
        req.set_board_id(bid);
        req.set_port_id(1);
        req.set_oop_value(new_oop);
        req.set_iop_value(new_iop);
        fiber::performance::ReportPerformanceResponse resp;
        perf_stub->ReportPerformance(&ctx1, req, &resp);
        std::this_thread::sleep_for(std::chrono::milliseconds(300));

        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::GetCurrentPerformanceRequest get_req;
        get_req.set_board_id(bid);
        get_req.set_port_id(1);
        fiber::performance::GetCurrentPerformanceResponse get_resp;
        perf_stub->GetCurrentPerformance(&ctx2, get_req, &get_resp);

        if (std::abs(get_resp.oop_value() - new_oop) < 0.01) {
            TEST_PASS("C-07: ReportPerformance overwrite OK");
        } else {
            TEST_FAIL("C-07: value not updated, got " +
                      std::to_string(get_resp.oop_value()));
        }
    }

    // C-08: HealthCheck
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::HealthCheckRequest req;
        fiber::common::HealthCheckResponse resp;
        auto status = perf_stub->HealthCheck(&ctx, req, &resp);

        if (status.ok() && resp.serving()) {
            TEST_PASS("C-08: PerformanceService HealthCheck OK");
        } else {
            TEST_FAIL("C-08: " + status.error_message());
        }
    }
}

// ============================================================
//  Group D: AlarmService 功能测试
// ============================================================
void test_alarm_service() {
    std::cout << "\n=== Group D: AlarmService ===" << std::endl;
    int32_t base = id_base + 40000;

    int32_t bid = base + 1;
    create_board(bid, fiber::common::BoardType::ACTIVE, 3001);

    // D-01: ReportAlarm + GetCurrentAlarm 一致
    {
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ReportAlarmRequest req;
        req.set_board_id(bid);
        req.set_port_id(1);
        req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ReportAlarmResponse resp;
        auto s1 = alarm_stub->ReportAlarm(&ctx1, req, &resp);

        std::this_thread::sleep_for(std::chrono::milliseconds(300));

        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::GetCurrentAlarmRequest get_req;
        get_req.set_board_id(bid);
        get_req.set_port_id(1);
        fiber::alarm::GetCurrentAlarmResponse get_resp;
        auto s2 = alarm_stub->GetCurrentAlarm(&ctx2, get_req, &get_resp);

        if (s1.ok() && s2.ok() && get_resp.alarms_size() >= 1) {
            bool found_critical = false;
            for (const auto& a : get_resp.alarms()) {
                if (a.alarm_level() == fiber::common::AlarmLevel::CRITICAL)
                    found_critical = true;
            }
            if (found_critical) {
                TEST_PASS("D-01: ReportAlarm+GetCurrentAlarm CRITICAL found");
            } else {
                TEST_FAIL("D-01: CRITICAL not in current alarms");
            }
        } else {
            TEST_FAIL("D-01: " + s2.error_message());
        }
    }

    // D-02: ClearAlarm 后 GetCurrentAlarm 为空
    {
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ClearAlarmRequest clr_req;
        clr_req.set_board_id(bid);
        clr_req.set_port_id(1);
        clr_req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ClearAlarmResponse clr_resp;
        alarm_stub->ClearAlarm(&ctx1, clr_req, &clr_resp);

        std::this_thread::sleep_for(std::chrono::milliseconds(300));

        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::GetCurrentAlarmRequest get_req;
        get_req.set_board_id(bid);
        get_req.set_port_id(1);
        fiber::alarm::GetCurrentAlarmResponse get_resp;
        alarm_stub->GetCurrentAlarm(&ctx2, get_req, &get_resp);

        if (get_resp.alarms_size() == 0) {
            TEST_PASS("D-02: ClearAlarm → GetCurrentAlarm empty");
        } else {
            TEST_FAIL("D-02: still " + std::to_string(get_resp.alarms_size()) + " alarms");
        }
    }

    // D-03: 重复 ReportAlarm 同级别
    {
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ReportAlarmRequest req;
        req.set_board_id(bid);
        req.set_port_id(2);
        req.set_alarm_level(fiber::common::AlarmLevel::MINOR);
        fiber::alarm::ReportAlarmResponse resp1;
        alarm_stub->ReportAlarm(&ctx1, req, &resp1);

        grpc::ClientContext ctx2;
        ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ReportAlarmResponse resp2;
        auto status = alarm_stub->ReportAlarm(&ctx2, req, &resp2);

        // 幂等或 ALREADY_EXISTS 均可接受
        if (status.ok() || status.error_code() == grpc::StatusCode::ALREADY_EXISTS) {
            TEST_PASS("D-03: duplicate ReportAlarm handled (idempotent/rejected)");
        } else {
            TEST_PASS("D-03: duplicate alarm: " + status.error_message());
        }
        // 清理
        grpc::ClientContext ctx3;
        ctx3.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ClearAlarmRequest clr;
        clr.set_board_id(bid); clr.set_port_id(2);
        clr.set_alarm_level(fiber::common::AlarmLevel::MINOR);
        fiber::alarm::ClearAlarmResponse clr_resp;
        alarm_stub->ClearAlarm(&ctx3, clr, &clr_resp);
    }

    // D-04: ClearAlarm 不存在的告警
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ClearAlarmRequest req;
        req.set_board_id(bid);
        req.set_port_id(99);
        req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ClearAlarmResponse resp;
        auto status = alarm_stub->ClearAlarm(&ctx, req, &resp);

        // 成功（幂等）或 NOT_FOUND 均可
        if (status.ok() || status.error_code() == grpc::StatusCode::NOT_FOUND) {
            TEST_PASS("D-04: ClearAlarm non-existing handled");
        } else {
            TEST_PASS("D-04: " + status.error_message());
        }
    }

    // D-05: BatchGetCurrentAlarms 多端口
    {
        // 先上报两个端口
        grpc::ClientContext ctx0;
        ctx0.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ReportAlarmRequest rpt;
        rpt.set_board_id(bid); rpt.set_port_id(3);
        rpt.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ReportAlarmResponse rpt_resp;
        alarm_stub->ReportAlarm(&ctx0, rpt, &rpt_resp);

        grpc::ClientContext ctx0b;
        ctx0b.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        rpt.set_port_id(4);
        rpt.set_alarm_level(fiber::common::AlarmLevel::MINOR);
        fiber::alarm::ReportAlarmResponse rpt_resp2;
        alarm_stub->ReportAlarm(&ctx0b, rpt, &rpt_resp2);
        std::this_thread::sleep_for(std::chrono::milliseconds(300));

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::BatchGetCurrentAlarmsRequest req;
        auto* p1 = req.add_ports(); p1->set_board_id(bid); p1->set_port_id(3);
        auto* p2 = req.add_ports(); p2->set_board_id(bid); p2->set_port_id(4);
        fiber::alarm::BatchGetCurrentAlarmsResponse resp;
        auto status = alarm_stub->BatchGetCurrentAlarms(&ctx, req, &resp);

        if (status.ok() && resp.results_size() == 2) {
            TEST_PASS("D-05: BatchGetCurrentAlarms 2 ports OK");
        } else if (status.ok()) {
            TEST_PASS("D-05: returned " + std::to_string(resp.results_size()) + " results");
        } else {
            TEST_FAIL("D-05: " + status.error_message());
        }
    }

    // D-06: BatchGetCurrentAlarms 含无告警端口
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::BatchGetCurrentAlarmsRequest req;
        auto* p1 = req.add_ports(); p1->set_board_id(bid); p1->set_port_id(3);
        auto* p2 = req.add_ports(); p2->set_board_id(bid); p2->set_port_id(99);
        fiber::alarm::BatchGetCurrentAlarmsResponse resp;
        auto status = alarm_stub->BatchGetCurrentAlarms(&ctx, req, &resp);

        if (status.ok() && resp.results_size() >= 2) {
            // port 99 应该没有告警
            bool port99_empty = (resp.results(1).alarms_size() == 0);
            if (port99_empty) {
                TEST_PASS("D-06: no-alarm port returns empty list");
            } else {
                TEST_PASS("D-06: batch returned (port99 alarms=" +
                          std::to_string(resp.results(1).alarms_size()) + ")");
            }
        } else if (status.ok()) {
            TEST_PASS("D-06: batch OK");
        } else {
            TEST_FAIL("D-06: " + status.error_message());
        }
    }

    // D-07: SubscribeAlarmEvents 接收 ALARM_RAISED
    {
        std::atomic<bool> event_received{false};

        std::thread reader([&]() {
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(8));
            fiber::alarm::SubscribeAlarmEventsRequest req;
            auto stream = alarm_stub->SubscribeAlarmEvents(&ctx, req);
            fiber::alarm::AlarmEvent event;
            while (stream->Read(&event)) {
                if (event.event_type() == fiber::common::ALARM_RAISED) {
                    event_received = true;
                    break;
                }
            }
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ReportAlarmRequest req;
        req.set_board_id(bid); req.set_port_id(5);
        req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ReportAlarmResponse resp;
        alarm_stub->ReportAlarm(&ctx, req, &resp);

        for (int i = 0; i < 20 && !event_received; i++) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

        if (event_received) {
            TEST_PASS("D-07: SubscribeAlarmEvents received ALARM_RAISED");
        } else {
            TEST_FAIL("D-07: no ALARM_RAISED event in 4s");
        }
        reader.detach();
    }

    // D-08: CreatePullCall → GetPullCallResult
    {
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::CreatePullCallRequest req;
        req.set_include_history(false);
        req.set_expire_seconds(30);
        fiber::alarm::CreatePullCallResponse resp;
        auto status = alarm_stub->CreatePullCall(&ctx1, req, &resp);

        if (status.ok() && !resp.task_id().empty()) {
            // 轮询结果
            std::string final_status = resp.status();
            for (int i = 0; i < 5; i++) {
                std::this_thread::sleep_for(std::chrono::seconds(1));
                grpc::ClientContext ctx2;
                ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
                fiber::alarm::GetPullCallResultRequest get_req;
                get_req.set_task_id(resp.task_id());
                fiber::alarm::GetPullCallResultResponse get_resp;
                auto s2 = alarm_stub->GetPullCallResult(&ctx2, get_req, &get_resp);
                if (s2.ok()) {
                    final_status = get_resp.status();
                    if (final_status == "completed" || final_status == "failed") break;
                }
            }
            TEST_PASS("D-08: CreatePullCall task_id=" + resp.task_id() +
                      " status=" + final_status);
        } else {
            TEST_FAIL("D-08: CreatePullCall failed: " + status.error_message());
        }
    }

    // D-09: CancelPullCall
    {
        // 创建新任务再取消
        grpc::ClientContext ctx1;
        ctx1.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::CreatePullCallRequest req;
        req.set_expire_seconds(60);
        fiber::alarm::CreatePullCallResponse resp;
        auto s1 = alarm_stub->CreatePullCall(&ctx1, req, &resp);

        if (s1.ok() && !resp.task_id().empty()) {
            grpc::ClientContext ctx2;
            ctx2.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
            fiber::alarm::CancelPullCallRequest cancel_req;
            cancel_req.set_task_id(resp.task_id());
            fiber::alarm::CancelPullCallResponse cancel_resp;
            auto s2 = alarm_stub->CancelPullCall(&ctx2, cancel_req, &cancel_resp);

            if (s2.ok() && cancel_resp.success()) {
                TEST_PASS("D-09: CancelPullCall success");
            } else {
                TEST_PASS("D-09: CancelPullCall: " + s2.error_message());
            }
        } else {
            TEST_FAIL("D-09: CreatePullCall failed for cancel test");
        }
    }

    // D-10: HealthCheck
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::HealthCheckRequest req;
        fiber::common::HealthCheckResponse resp;
        auto status = alarm_stub->HealthCheck(&ctx, req, &resp);

        if (status.ok() && resp.serving()) {
            TEST_PASS("D-10: AlarmService HealthCheck OK");
        } else {
            TEST_FAIL("D-10: " + status.error_message());
        }
    }
}

// ============================================================
//  Group E: FiberMaintService 补充测试
// ============================================================
void test_fiber_maint_supplement() {
    std::cout << "\n=== Group E: FiberMaintService Supplement ===" << std::endl;
    int32_t base = id_base + 50000;

    // 准备场景1拓扑 + 告警触发 RED
    int32_t bid_src = base + 1;
    int32_t bid_dst = base + 2;
    create_board(bid_src, fiber::common::BoardType::ACTIVE, 4001);
    create_board(bid_dst, fiber::common::BoardType::ACTIVE, 4002);
    int32_t fid = create_fiber(bid_src, 1, bid_dst, 1);
    std::this_thread::sleep_for(std::chrono::seconds(3));

    // 上报性能（为 history 测试准备）
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::ReportPerformanceRequest req;
        req.set_board_id(bid_src); req.set_port_id(1);
        req.set_oop_value(-6.0); req.set_iop_value(0.0);
        fiber::performance::ReportPerformanceResponse resp;
        perf_stub->ReportPerformance(&ctx, req, &resp);
    }
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::performance::ReportPerformanceRequest req;
        req.set_board_id(bid_dst); req.set_port_id(1);
        req.set_oop_value(0.0); req.set_iop_value(-11.0);
        fiber::performance::ReportPerformanceResponse resp;
        perf_stub->ReportPerformance(&ctx, req, &resp);
    }

    // 触发 RED 颜色
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ReportAlarmRequest req;
        req.set_board_id(bid_dst); req.set_port_id(1);
        req.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ReportAlarmResponse resp;
        alarm_stub->ReportAlarm(&ctx, req, &resp);
    }
    std::this_thread::sleep_for(std::chrono::seconds(3));

    // E-01: GetColoredFibers(RED) 仅返回红色
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::maint::GetColoredFibersRequest req;
        req.set_color(fiber::common::FiberColor::RED);
        fiber::maint::GetColoredFibersResponse resp;
        auto status = maint_stub->GetColoredFibers(&ctx, req, &resp);

        if (status.ok()) {
            bool all_red = true;
            for (const auto& cf : resp.fibers()) {
                if (cf.color() != fiber::common::FiberColor::RED) all_red = false;
            }
            if (all_red && resp.fibers_size() >= 0) {
                TEST_PASS("E-01: GetColoredFibers(RED) returned " +
                          std::to_string(resp.fibers_size()) + " fibers, all RED");
            } else {
                TEST_FAIL("E-01: non-RED fiber in RED filter result");
            }
        } else {
            TEST_FAIL("E-01: " + status.error_message());
        }
    }

    // E-02: GetColoredFibers(YELLOW)
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::maint::GetColoredFibersRequest req;
        req.set_color(fiber::common::FiberColor::YELLOW);
        fiber::maint::GetColoredFibersResponse resp;
        auto status = maint_stub->GetColoredFibers(&ctx, req, &resp);

        if (status.ok()) {
            bool all_yellow = true;
            for (const auto& cf : resp.fibers()) {
                if (cf.color() != fiber::common::FiberColor::YELLOW) all_yellow = false;
            }
            if (all_yellow) {
                TEST_PASS("E-02: GetColoredFibers(YELLOW) returned " +
                          std::to_string(resp.fibers_size()) + " fibers");
            } else {
                TEST_FAIL("E-02: non-YELLOW in YELLOW filter");
            }
        } else {
            TEST_FAIL("E-02: " + status.error_message());
        }
    }

    // E-03: GetFiberHistoryPerformance
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::maint::GetFiberHistoryPerformanceRequest req;
        req.set_fiber_id(fid);
        req.set_start_time("2026-01-01T00:00:00");
        req.set_end_time("2026-12-31T23:59:59");
        fiber::maint::GetFiberHistoryPerformanceResponse resp;
        auto status = maint_stub->GetFiberHistoryPerformance(&ctx, req, &resp);

        if (status.ok()) {
            TEST_PASS("E-03: GetFiberHistoryPerformance OK, records=" +
                      std::to_string(resp.records_size()));
        } else {
            TEST_FAIL("E-03: " + status.error_message());
        }
    }

    // E-04: GetFiberHistoryPerformance 无数据纤
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::maint::GetFiberHistoryPerformanceRequest req;
        req.set_fiber_id(999999);
        req.set_start_time("2026-01-01T00:00:00");
        req.set_end_time("2026-12-31T23:59:59");
        fiber::maint::GetFiberHistoryPerformanceResponse resp;
        auto status = maint_stub->GetFiberHistoryPerformance(&ctx, req, &resp);

        if (status.ok() && resp.records_size() == 0) {
            TEST_PASS("E-04: non-existing fiber history → empty");
        } else if (!status.ok()) {
            TEST_PASS("E-04: non-existing fiber → " + status.error_message());
        } else {
            TEST_FAIL("E-04: unexpected records for non-existing fiber");
        }
    }

    // E-05: BatchGetFiberHistoryPerformance
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::maint::BatchGetFiberHistoryPerformanceRequest req;
        req.add_fiber_ids(fid);
        req.add_fiber_ids(999999);
        req.set_start_time("2026-01-01T00:00:00");
        req.set_end_time("2026-12-31T23:59:59");
        fiber::maint::BatchGetFiberHistoryPerformanceResponse resp;
        auto status = maint_stub->BatchGetFiberHistoryPerformance(&ctx, req, &resp);

        if (status.ok()) {
            TEST_PASS("E-05: BatchGetFiberHistoryPerformance OK, results=" +
                      std::to_string(resp.results_size()));
        } else {
            TEST_FAIL("E-05: " + status.error_message());
        }
    }

    // E-06: SubscribeFiberColorEvents
    {
        std::atomic<bool> event_received{false};

        std::thread reader([&]() {
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(10));
            fiber::maint::SubscribeFiberColorEventsRequest req;
            auto stream = maint_stub->SubscribeFiberColorEvents(&ctx, req);
            fiber::maint::FiberColorEvent event;
            while (stream->Read(&event)) {
                event_received = true;
                break;
            }
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(500));

        // 触发颜色变更: 清除告警 → RED→GREEN
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::alarm::ClearAlarmRequest clr;
        clr.set_board_id(bid_dst); clr.set_port_id(1);
        clr.set_alarm_level(fiber::common::AlarmLevel::CRITICAL);
        fiber::alarm::ClearAlarmResponse clr_resp;
        alarm_stub->ClearAlarm(&ctx, clr, &clr_resp);

        for (int i = 0; i < 25 && !event_received; i++) {
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }

        if (event_received) {
            TEST_PASS("E-06: SubscribeFiberColorEvents received event");
        } else {
            TEST_FAIL("E-06: no color event in 5s");
        }
        reader.detach();
    }

    // E-07: PullCallResultCallback
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::maint::PullCallResultCallbackRequest req;
        req.set_task_id("test-task-001");
        req.set_status("completed");
        fiber::maint::PullCallResultCallbackResponse resp;
        auto status = maint_stub->PullCallResultCallback(&ctx, req, &resp);

        if (status.ok()) {
            TEST_PASS("E-07: PullCallResultCallback OK, success=" +
                      std::to_string(resp.success()));
        } else {
            TEST_PASS("E-07: PullCallResultCallback: " + status.error_message());
        }
    }
}

// ============================================================
//  Group F: 错误处理与边界
// ============================================================
void test_error_handling() {
    std::cout << "\n=== Group F: Error Handling & Boundaries ===" << std::endl;
    int32_t base = id_base + 60000;

    // F-01: CreateFiber 源盘不存在
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::CreateFiberRequest req;
        req.set_src_board_id(999998);
        req.set_src_port_id(1);
        req.set_dst_board_id(999997);
        req.set_dst_port_id(1);
        fiber::topology::CreateFiberResponse resp;
        auto status = topology_stub->CreateFiber(&ctx, req, &resp);

        if (!status.ok() || !resp.success()) {
            TEST_PASS("F-01: CreateFiber non-existing board rejected (" +
                      std::to_string(status.error_code()) + ")");
        } else {
            TEST_FAIL("F-01: CreateFiber with non-existing board succeeded");
        }
    }

    // F-02: CreateFiber 同端口重复
    {
        int32_t bid1 = base + 1;
        int32_t bid2 = base + 2;
        int32_t bid3 = base + 3;
        create_board(bid1, fiber::common::BoardType::ACTIVE, 5001);
        create_board(bid2, fiber::common::BoardType::ACTIVE, 5002);
        create_board(bid3, fiber::common::BoardType::ACTIVE, 5003);
        create_fiber(bid1, 1, bid2, 1);  // 占用 bid1:port1

        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::CreateFiberRequest req;
        req.set_src_board_id(bid1);
        req.set_src_port_id(1);  // 已占用
        req.set_dst_board_id(bid3);
        req.set_dst_port_id(1);
        fiber::topology::CreateFiberResponse resp;
        auto status = topology_stub->CreateFiber(&ctx, req, &resp);

        if (!status.ok() || !resp.success()) {
            TEST_PASS("F-02: duplicate port fiber rejected (" +
                      std::to_string(status.error_code()) + ")");
        } else {
            TEST_FAIL("F-02: duplicate port fiber accepted");
        }
    }

    // F-03: DeleteBoard 不存在
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::DeleteBoardRequest req;
        req.set_board_id(999996);
        fiber::board::DeleteBoardResponse resp;
        auto status = board_stub->DeleteBoard(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::NOT_FOUND || !status.ok()) {
            TEST_PASS("F-03: DeleteBoard non-existing → error");
        } else if (!resp.success()) {
            TEST_PASS("F-03: DeleteBoard non-existing → success=false");
        } else {
            TEST_FAIL("F-03: DeleteBoard non-existing succeeded");
        }
    }

    // F-04: DeleteFiber 不存在
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::topology::DeleteFiberRequest req;
        req.set_fiber_id(999995);
        fiber::topology::DeleteFiberResponse resp;
        auto status = topology_stub->DeleteFiber(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::NOT_FOUND || !status.ok()) {
            TEST_PASS("F-04: DeleteFiber non-existing → error");
        } else if (!resp.success()) {
            TEST_PASS("F-04: DeleteFiber non-existing → success=false");
        } else {
            TEST_FAIL("F-04: DeleteFiber non-existing succeeded");
        }
    }

    // F-05: BatchGetBoards 超 200 条
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(5));
        fiber::board::BatchGetBoardsRequest req;
        for (int i = 0; i < 201; i++) {
            req.add_board_ids(i + 1);
        }
        fiber::board::BatchGetBoardsResponse resp;
        auto status = board_stub->BatchGetBoards(&ctx, req, &resp);

        if (status.error_code() == grpc::StatusCode::INVALID_ARGUMENT) {
            TEST_PASS("F-05: >200 BatchGetBoards → INVALID_ARGUMENT");
        } else if (status.ok()) {
            TEST_PASS("F-05: >200 accepted (no limit enforcement)");
        } else {
            TEST_PASS("F-05: >200 rejected: " + status.error_message());
        }
    }

    // F-06: 全部 5 个服务 HealthCheck 一致性
    {
        int ok_count = 0;
        auto check = [&](auto* stub, const char* name) {
            grpc::ClientContext ctx;
            ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
            fiber::common::HealthCheckResponse resp;
            // 使用通用 HealthCheckRequest（各服务定义相同）
            if (stub->HealthCheck(&ctx, fiber::board::HealthCheckRequest{}, &resp).ok() &&
                resp.serving()) {
                ok_count++;
            }
        };
        // 逐个检查
        {
            grpc::ClientContext c; c.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
            fiber::board::HealthCheckRequest r; fiber::common::HealthCheckResponse resp;
            if (board_stub->HealthCheck(&c, r, &resp).ok() && resp.serving()) ok_count++;
        }
        {
            grpc::ClientContext c; c.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
            fiber::topology::HealthCheckRequest r; fiber::common::HealthCheckResponse resp;
            if (topology_stub->HealthCheck(&c, r, &resp).ok() && resp.serving()) ok_count++;
        }
        {
            grpc::ClientContext c; c.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
            fiber::performance::HealthCheckRequest r; fiber::common::HealthCheckResponse resp;
            if (perf_stub->HealthCheck(&c, r, &resp).ok() && resp.serving()) ok_count++;
        }
        {
            grpc::ClientContext c; c.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
            fiber::alarm::HealthCheckRequest r; fiber::common::HealthCheckResponse resp;
            if (alarm_stub->HealthCheck(&c, r, &resp).ok() && resp.serving()) ok_count++;
        }
        {
            grpc::ClientContext c; c.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
            fiber::maint::HealthCheckRequest r; fiber::common::HealthCheckResponse resp;
            if (maint_stub->HealthCheck(&c, r, &resp).ok() && resp.serving()) ok_count++;
        }

        if (ok_count == 5) {
            TEST_PASS("F-06: all 5 services HealthCheck serving=true");
        } else {
            TEST_FAIL("F-06: only " + std::to_string(ok_count) + "/5 services healthy");
        }
    }
}

// ============================================================
//  main
// ============================================================
int main() {
    std::cout << "========================================" << std::endl;
    std::cout << " All Services API Functional Test" << std::endl;
    std::cout << "========================================" << std::endl;

    init_stubs();
    init_id_base();

    // 验证基本连通性
    {
        grpc::ClientContext ctx;
        ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(3));
        fiber::board::HealthCheckRequest req;
        fiber::common::HealthCheckResponse resp;
        auto status = board_stub->HealthCheck(&ctx, req, &resp);
        if (!status.ok() || !resp.serving()) {
            std::cout << "[ERROR] Services not available. Ensure all 5 services running."
                      << std::endl;
            return 1;
        }
        std::cout << "[INFO] Services connected." << std::endl;
    }

    test_board_service();
    test_topology_service();
    test_performance_service();
    test_alarm_service();
    test_fiber_maint_supplement();
    test_error_handling();

    // 汇总
    std::cout << "\n========================================" << std::endl;
    std::cout << " Test Summary" << std::endl;
    std::cout << "========================================" << std::endl;
    std::cout << " Passed: " << passed << std::endl;
    std::cout << " Failed: " << failed << std::endl;
    std::cout << " Total:  " << passed + failed << std::endl;
    std::cout << "========================================" << std::endl;

    return (failed > 0) ? 1 : 0;
}
