#pragma once

#include "common/common.h"
#include "board.grpc.pb.h"
#include "topology.grpc.pb.h"
#include <google/protobuf/repeated_field.h>
#include <memory>
#include <string>
#include <unordered_set>

/**
 * 场景解析插件（SceneResolver）
 * 
 * 将场景判断逻辑封装为可复用组件，供 TopologyService、FiberMaintService 等服务调用。
 *
 * 场景类型说明：
 *   scene_type = 1：网元间连纤两端均为有源盘
 *   scene_type = 2：网元间连纤至少一端为无源盘（需查询网元内连纤）
 *
 * 使用方式：
 *   SceneResolver resolver;
 *   resolver.set_board_service_addr("localhost:50051");
 *   fiber::topology::FiberScene scene;
 *   if (resolver.resolveScene(fiber_id, &scene)) { ... }
 */
class SceneResolver {
public:
    SceneResolver();

    // 设置 BoardService gRPC 地址
    void set_board_service_addr(const std::string& addr);

    // 获取单板类型（有源/无源）
    fiber::common::BoardType getBoardType(int32_t board_id);

    // 获取单板完整信息
    bool getBoardInfo(int32_t board_id, fiber::common::BoardInfo* info);

    // 解析完整场景：填充 inter_ne_fiber、active_boards、ne_internal_fibers、passive_boards
    // 返回 true 表示成功，false 表示连纤不存在或数据库错误
    bool resolveScene(int32_t fiber_id, fiber::topology::FiberSceneInfo* scene);

    // 轻量级：仅获取场景类型（不查询内部连纤和单板详情）
    // 返回 1 或 2，失败返回 0
    int32_t getSceneType(int32_t fiber_id);

    // 获取网元内连纤（scene_type=2 时使用）
    // 输入网元间连纤的 src_board_id 和 dst_board_id，返回关联的网元内连纤
    bool getNeInternalFibers(int32_t src_board_id, int32_t dst_board_id,
                             google::protobuf::RepeatedPtrField<fiber::common::FiberInfo>* internal_fibers,
                             std::unordered_set<int32_t>* passive_board_ids);

private:
    std::string board_service_addr_;
    std::shared_ptr<fiber::board::BoardService::Stub> board_stub_;

    std::shared_ptr<fiber::board::BoardService::Stub> getBoardStub();
};
