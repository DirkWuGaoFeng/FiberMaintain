#include "scene_resolver.h"
#include <mysql.h>
#include <chrono>

SceneResolver::SceneResolver()
    : board_service_addr_("localhost:50051") {}

void SceneResolver::set_board_service_addr(const std::string& addr) {
    board_service_addr_ = addr;
    board_stub_.reset();
}

std::shared_ptr<fiber::board::BoardService::Stub> SceneResolver::getBoardStub() {
    if (!board_stub_) {
        auto channel = grpc::CreateChannel(board_service_addr_, grpc::InsecureChannelCredentials());
        board_stub_ = fiber::board::BoardService::NewStub(channel);
    }
    return board_stub_;
}

fiber::common::BoardType SceneResolver::getBoardType(int32_t board_id) {
    fiber::common::BoardInfo info;
    if (getBoardInfo(board_id, &info)) {
        return info.board_type();
    }
    return fiber::common::BoardType::BOARD_TYPE_UNSPECIFIED;
}

bool SceneResolver::getBoardInfo(int32_t board_id, fiber::common::BoardInfo* info) {
    auto stub = getBoardStub();
    fiber::board::GetBoardRequest req;
    req.set_board_id(board_id);
    fiber::board::GetBoardResponse resp;

    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::seconds(2));

    auto status = stub->GetBoard(&ctx, req, &resp);
    if (status.ok()) {
        *info = resp.board();
        return true;
    }
    return false;
}

int32_t SceneResolver::getSceneType(int32_t fiber_id) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return 0;

    char sql[256];
    sprintf(sql, "SELECT src_board_id, dst_board_id FROM fiber_connections WHERE fiber_id = %d", fiber_id);

    if (mysql_query(conn.get(), sql) != 0) return 0;

    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    if (!row) {
        mysql_free_result(res);
        return 0;
    }

    int32_t src_board_id = std::stoi(row[0]);
    int32_t dst_board_id = std::stoi(row[1]);
    mysql_free_result(res);

    auto src_type = getBoardType(src_board_id);
    auto dst_type = getBoardType(dst_board_id);

    if (src_type == fiber::common::BoardType::ACTIVE && dst_type == fiber::common::BoardType::ACTIVE) {
        return 1;
    }
    return 2;
}

bool SceneResolver::getNeInternalFibers(int32_t src_board_id, int32_t dst_board_id,
                                         google::protobuf::RepeatedPtrField<fiber::common::FiberInfo>* internal_fibers,
                                         std::unordered_set<int32_t>* passive_board_ids) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return false;

    char sql[512];
    sprintf(sql,
            "SELECT fiber_id, src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id "
            "FROM fiber_connections WHERE src_ne_id = dst_ne_id AND "
            "(src_board_id IN (%d,%d) OR dst_board_id IN (%d,%d))",
            src_board_id, dst_board_id, src_board_id, dst_board_id);

    if (mysql_query(conn.get(), sql) != 0) return false;

    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row;
    while ((row = mysql_fetch_row(res)) != nullptr) {
        fiber::common::FiberInfo fiber_info;
        fiber_info.set_fiber_id(std::stoi(row[0]));
        fiber_info.set_src_board_id(std::stoi(row[1]));
        fiber_info.set_src_port_id(std::stoi(row[2]));
        fiber_info.set_src_ne_id(std::stoi(row[3]));
        fiber_info.set_dst_board_id(std::stoi(row[4]));
        fiber_info.set_dst_port_id(std::stoi(row[5]));
        fiber_info.set_dst_ne_id(std::stoi(row[6]));
        internal_fibers->Add()->CopyFrom(fiber_info);

        if (getBoardType(std::stoi(row[1])) == fiber::common::BoardType::PASSIVE) {
            passive_board_ids->insert(std::stoi(row[1]));
        }
        if (getBoardType(std::stoi(row[4])) == fiber::common::BoardType::PASSIVE) {
            passive_board_ids->insert(std::stoi(row[4]));
        }
    }
    mysql_free_result(res);
    return true;
}

bool SceneResolver::resolveScene(int32_t fiber_id, fiber::topology::FiberSceneInfo* scene) {
    auto conn = DBConnectionPool::instance().get_connection();
    if (!conn) return false;

    // 1. 查询网元间连纤
    char sql[256];
    sprintf(sql,
            "SELECT fiber_id, src_board_id, src_port_id, src_ne_id, dst_board_id, dst_port_id, dst_ne_id "
            "FROM fiber_connections WHERE fiber_id = %d", fiber_id);

    if (mysql_query(conn.get(), sql) != 0) return false;

    MYSQL_RES* res = mysql_store_result(conn.get());
    MYSQL_ROW row = mysql_fetch_row(res);
    if (!row) {
        mysql_free_result(res);
        return false;
    }

    fiber::common::FiberInfo inter_ne_fiber;
    inter_ne_fiber.set_fiber_id(std::stoi(row[0]));
    inter_ne_fiber.set_src_board_id(std::stoi(row[1]));
    inter_ne_fiber.set_src_port_id(std::stoi(row[2]));
    inter_ne_fiber.set_src_ne_id(std::stoi(row[3]));
    inter_ne_fiber.set_dst_board_id(std::stoi(row[4]));
    inter_ne_fiber.set_dst_port_id(std::stoi(row[5]));
    inter_ne_fiber.set_dst_ne_id(std::stoi(row[6]));
    mysql_free_result(res);

    int32_t src_board_id = inter_ne_fiber.src_board_id();
    int32_t dst_board_id = inter_ne_fiber.dst_board_id();

    // 2. 判断场景类型
    auto src_type = getBoardType(src_board_id);
    auto dst_type = getBoardType(dst_board_id);

    int32_t scene_type = (src_type == fiber::common::BoardType::ACTIVE &&
                          dst_type == fiber::common::BoardType::ACTIVE) ? 1 : 2;

    scene->set_scene_type(scene_type);
    scene->set_inter_ne_fiber_id(fiber_id);
    scene->set_allocated_inter_ne_fiber(new fiber::common::FiberInfo(inter_ne_fiber));

    // 3. 填充有源盘信息（场景1和2都可能需要）
    if (src_type == fiber::common::BoardType::ACTIVE) {
        fiber::common::BoardInfo board;
        if (getBoardInfo(src_board_id, &board)) {
            scene->set_allocated_src_active_board(new fiber::common::BoardInfo(board));
        }
    }
    if (dst_type == fiber::common::BoardType::ACTIVE) {
        fiber::common::BoardInfo board;
        if (getBoardInfo(dst_board_id, &board)) {
            scene->set_allocated_dst_active_board(new fiber::common::BoardInfo(board));
        }
    }

    // 4. 场景2：查询网元内连纤和无源盘
    if (scene_type == 2) {
        std::unordered_set<int32_t> passive_board_ids;
        if (src_type == fiber::common::BoardType::PASSIVE) {
            passive_board_ids.insert(src_board_id);
        }
        if (dst_type == fiber::common::BoardType::PASSIVE) {
            passive_board_ids.insert(dst_board_id);
        }

        getNeInternalFibers(src_board_id, dst_board_id,
                            scene->mutable_ne_internal_fibers(),
                            &passive_board_ids);

        // 填充无源盘信息
        for (int32_t board_id : passive_board_ids) {
            fiber::common::BoardInfo board;
            if (getBoardInfo(board_id, &board)) {
                scene->add_passive_boards()->CopyFrom(board);
            }
        }

        // 5. 场景2补充：从网元内连纤中找出源宿有源盘
        // 当网元间连纤端点为无源盘时，有源盘通过网元内连纤连接
        int32_t src_ne_id = inter_ne_fiber.src_ne_id();
        int32_t dst_ne_id = inter_ne_fiber.dst_ne_id();

        for (const auto& f : scene->ne_internal_fibers()) {
            // 检查 src_board 是否是有源盘（不在 passive_boards 中）
            if (passive_board_ids.find(f.src_board_id()) == passive_board_ids.end()) {
                fiber::common::BoardInfo board;
                if (getBoardInfo(f.src_board_id(), &board) &&
                    board.board_type() == fiber::common::BoardType::ACTIVE) {
                    if (f.src_ne_id() == src_ne_id && !scene->has_src_active_board()) {
                        scene->set_allocated_src_active_board(new fiber::common::BoardInfo(board));
                    } else if (f.src_ne_id() == dst_ne_id && !scene->has_dst_active_board()) {
                        scene->set_allocated_dst_active_board(new fiber::common::BoardInfo(board));
                    }
                }
            }
            // 检查 dst_board 是否是有源盘
            if (passive_board_ids.find(f.dst_board_id()) == passive_board_ids.end()) {
                fiber::common::BoardInfo board;
                if (getBoardInfo(f.dst_board_id(), &board) &&
                    board.board_type() == fiber::common::BoardType::ACTIVE) {
                    if (f.dst_ne_id() == src_ne_id && !scene->has_src_active_board()) {
                        scene->set_allocated_src_active_board(new fiber::common::BoardInfo(board));
                    } else if (f.dst_ne_id() == dst_ne_id && !scene->has_dst_active_board()) {
                        scene->set_allocated_dst_active_board(new fiber::common::BoardInfo(board));
                    }
                }
            }
        }
    }

    return true;
}
