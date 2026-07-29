#pragma once

/**
 * @file color_strategy.h
 * @brief Layer 3 - 颜色策略体系（策略模式）
 *
 * IColorStrategy 接口 + 4 种场景策略 + ScenarioRegistry 路由器。
 * 将 calculate_color() 从巨型 if-else 重构为多态分发。
 */

#include "types.h"
#include <memory>

namespace fiber_maint {

/// 告警摘要（由调用方从 alarm_cache 中查询后传入）
struct PortAlarmStatus {
    bool has_critical = false;
    bool has_minor    = false;
};

/// 颜色评估输入
struct ColorEvalInput {
    FiberTopologyInfo topo;
    /// 各 AlarmTarget 对应的告警状态（与 topo 的告警目标一一对应）
    std::vector<std::pair<AlarmRole, PortAlarmStatus>> alarm_statuses;
};

// ============================================================
//  IColorStrategy 接口
// ============================================================

class IColorStrategy {
public:
    virtual ~IColorStrategy() = default;

    /// 是否可以跳过计算（如 Case C 固定 GREEN）
    virtual bool can_skip(const ColorEvalInput& input) const = 0;

    /// 评估颜色
    virtual FiberColor evaluate(const ColorEvalInput& input) const = 0;

    /// 声明告警依赖（哪些端口的告警变化会触发重算）
    virtual std::vector<AlarmRole> declare_alarm_dependencies() const = 0;
};

// ============================================================
//  Scene1Strategy — 场景1：宿端有源盘
// ============================================================

class Scene1Strategy : public IColorStrategy {
public:
    bool can_skip(const ColorEvalInput& input) const override { return false; }
    FiberColor evaluate(const ColorEvalInput& input) const override;
    std::vector<AlarmRole> declare_alarm_dependencies() const override {
        return {AlarmRole::DST_ACTIVE};
    }
};

// ============================================================
//  Scene2CaseAStrategy — 场景2 Case A：B + A2 双路（9 种组合）
// ============================================================

class Scene2CaseAStrategy : public IColorStrategy {
public:
    bool can_skip(const ColorEvalInput& input) const override { return false; }
    FiberColor evaluate(const ColorEvalInput& input) const override;
    std::vector<AlarmRole> declare_alarm_dependencies() const override {
        return {AlarmRole::PORT2_PEER, AlarmRole::PORT3_PEER};
    }
};

// ============================================================
//  Scene2CaseBStrategy — 场景2 Case B：仅 B
// ============================================================

class Scene2CaseBStrategy : public IColorStrategy {
public:
    bool can_skip(const ColorEvalInput& input) const override { return false; }
    FiberColor evaluate(const ColorEvalInput& input) const override;
    std::vector<AlarmRole> declare_alarm_dependencies() const override {
        return {AlarmRole::PORT2_PEER};
    }
};

// ============================================================
//  Scene2CaseCStrategy — 场景2 Case C：固定 GREEN
// ============================================================

class Scene2CaseCStrategy : public IColorStrategy {
public:
    bool can_skip(const ColorEvalInput& input) const override { return true; }
    FiberColor evaluate(const ColorEvalInput& input) const override {
        return FiberColor::GREEN;
    }
    std::vector<AlarmRole> declare_alarm_dependencies() const override {
        return {};
    }
};

// ============================================================
//  ScenarioRegistry — 场景路由器
// ============================================================

class ScenarioRegistry {
public:
    ScenarioRegistry();

    /// 根据拓扑匹配策略
    const IColorStrategy* match(const FiberTopologyInfo& topo) const;

private:
    std::unique_ptr<Scene1Strategy>      scene1_;
    std::unique_ptr<Scene2CaseAStrategy> scene2a_;
    std::unique_ptr<Scene2CaseBStrategy> scene2b_;
    std::unique_ptr<Scene2CaseCStrategy> scene2c_;
};

} // namespace fiber_maint
