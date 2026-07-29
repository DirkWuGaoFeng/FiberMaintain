/**
 * @file color_strategy.cpp
 * @brief Layer 3 - 颜色策略实现
 *
 * 完整移植原 calculate_color() 逻辑，按策略模式拆分。
 *
 * 场景2 Case A 9种组合（含 R-23 单侧紧急=绿色规则）:
 *   B\C    | 无告警  | MINOR   | CRITICAL
 *   -------+---------+---------+----------
 *   无告警  | GREEN  | YELLOW  | GREEN(R-23)
 *   MINOR  | YELLOW  | YELLOW  | YELLOW
 *   CRITICAL| GREEN(R-23)| YELLOW | RED
 */

#include "color_strategy.h"

namespace fiber_maint {

// ────────────────── 辅助函数 ──────────────────

static PortAlarmStatus find_alarm(
        const std::vector<std::pair<AlarmRole, PortAlarmStatus>>& statuses,
        AlarmRole role) {
    for (const auto& [r, s] : statuses) {
        if (r == role) return s;
    }
    return {};
}

// ────────────────── Scene1Strategy ──────────────────

FiberColor Scene1Strategy::evaluate(const ColorEvalInput& input) const {
    auto alarm = find_alarm(input.alarm_statuses, AlarmRole::DST_ACTIVE);

    if (alarm.has_critical) return FiberColor::RED;
    if (alarm.has_minor)    return FiberColor::YELLOW;
    return FiberColor::GREEN;
}

// ────────────────── Scene2CaseAStrategy ──────────────────

FiberColor Scene2CaseAStrategy::evaluate(const ColorEvalInput& input) const {
    auto alarm_B  = find_alarm(input.alarm_statuses, AlarmRole::PORT2_PEER);
    auto alarm_A2 = find_alarm(input.alarm_statuses, AlarmRole::PORT3_PEER);

    bool B_crit  = alarm_B.has_critical;
    bool B_minor = alarm_B.has_minor;
    bool A2_crit  = alarm_A2.has_critical;
    bool A2_minor = alarm_A2.has_minor;

    // 双路均严重告警 → RED
    if (B_crit && A2_crit) {
        return FiberColor::RED;
    }

    // 任一侧有 MINOR 告警 → YELLOW（含 CRITICAL+MINOR 组合）
    if (B_minor || A2_minor) {
        return FiberColor::YELLOW;
    }
    if ((B_crit && A2_minor) || (A2_crit && B_minor)) {
        return FiberColor::YELLOW;
    }

    // R-23 单侧紧急规则：仅一侧 CRITICAL，另一侧无告警 → GREEN
    // （紧急侧已有备用路径，不影响主路）
    if (B_crit && !A2_crit && !A2_minor) {
        return FiberColor::GREEN;
    }
    if (A2_crit && !B_crit && !B_minor) {
        return FiberColor::GREEN;
    }

    return FiberColor::GREEN;
}

// ────────────────── Scene2CaseBStrategy ──────────────────

FiberColor Scene2CaseBStrategy::evaluate(const ColorEvalInput& input) const {
    auto alarm_B = find_alarm(input.alarm_statuses, AlarmRole::PORT2_PEER);

    if (alarm_B.has_critical) return FiberColor::RED;
    if (alarm_B.has_minor)    return FiberColor::YELLOW;
    return FiberColor::GREEN;
}

// ────────────────── ScenarioRegistry ──────────────────

ScenarioRegistry::ScenarioRegistry()
    : scene1_(std::make_unique<Scene1Strategy>())
    , scene2a_(std::make_unique<Scene2CaseAStrategy>())
    , scene2b_(std::make_unique<Scene2CaseBStrategy>())
    , scene2c_(std::make_unique<Scene2CaseCStrategy>()) {}

const IColorStrategy* ScenarioRegistry::match(
        const FiberTopologyInfo& topo) const {
    if (topo.scene_type == SceneType::SCENE_1) {
        return scene1_.get();
    }

    // SCENE_2
    switch (topo.scenario_case) {
    case ScenarioCase::CASE_A: return scene2a_.get();
    case ScenarioCase::CASE_B: return scene2b_.get();
    case ScenarioCase::CASE_C: return scene2c_.get();
    default:                   return scene1_.get(); // fallback
    }
}

} // namespace fiber_maint
