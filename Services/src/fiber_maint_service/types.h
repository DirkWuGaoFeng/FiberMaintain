#pragma once

/**
 * @file types.h
 * @brief Layer 0 - 核心数据结构定义（FiberMaintService v4.0 四层架构）
 *
 * 所有枚举、结构体、轻量容器的统一定义点。
 * Layer 1~3 以及 FiberMaintServiceImpl 均依赖此文件。
 */

#include <cstdint>
#include <cstddef>
#include <vector>
#include <optional>
#include <chrono>
#include <functional>
#include <string>

namespace fiber_maint {

// ============================================================
//  枚举类型
// ============================================================

/// 单盘类型
enum class BoardType : uint8_t {
    ACTIVE   = 0,  ///< 有源盘（Port-1 连接网元间连纤）
    PASSIVE  = 1   ///< 无源盘（Port-2/3 连接网元内连纤）
};

/// 场景类型
enum class SceneType : uint8_t {
    SCENE_1  = 1,  ///< 场景1：宿端有源盘，无无源盘中继
    SCENE_2  = 2   ///< 场景2：宿端无源盘，有 Port-2/3 中继
};

/// 场景2子场景
enum class ScenarioCase : uint8_t {
    CASE_0   = 0,  ///< 场景1专用（场景2不适用）
    CASE_A   = 1,  ///< Case A：Port-2 + Port-3 双路（B + A2）
    CASE_B   = 2,  ///< Case B：仅 Port-2 单路（仅 B）
    CASE_C   = 3   ///< Case C：无 Port-2 连纤 → 固定 GREEN
};

/// 告警依赖角色（用于 DependencyEntry）
enum class AlarmRole : uint8_t {
    DST_ACTIVE  = 0,  ///< 宿端有源盘 Port-1 告警（场景1/2B）
    PORT2_PEER  = 1,  ///< Port-2 对端 Board-B Port-1 告警（场景2A 主路）
    PORT3_PEER  = 2   ///< Port-3 对端 Board-A2 Port-1 告警（场景2A 备路）
};

/// 光纤颜色:与proto保持一致
enum class FiberColor : int8_t {
    UNKNOWN = 0,
    GREEN  = 1,
    RED = 2,
    YELLOW = 3
};

/// 光纤颜色
const std::string FiberColorStr[] = {
    "UNKNOWN",
    "GREEN",
    "RED",
    "YELLOW"
};

// ============================================================
//  PortKey — 端口唯一标识（board_id + port_id）
// ============================================================

struct PortKey {
    int32_t board_id = 0;
    int32_t port_id  = 0;

    bool operator==(const PortKey& o) const noexcept {
        return board_id == o.board_id && port_id == o.port_id;
    }
    bool operator!=(const PortKey& o) const noexcept {
        return !(*this == o);
    }
};

struct PortKeyHash {
    size_t operator()(const PortKey& k) const noexcept {
        // board_id 高 32 位, port_id 低 32 位
        return std::hash<int64_t>()(
            (static_cast<int64_t>(k.board_id) << 32) |
            static_cast<uint32_t>(k.port_id));
    }
};

// ============================================================
//  PeerInfo — 无源盘对端信息
// ============================================================

struct PeerInfo {
    int32_t board_id = 0;   ///< 对端单盘 ID
    int32_t port_id  = 0;   ///< 对端端口（通常为 1）
    int32_t via_port = 0;   ///< 经由的无源盘端口（2 或 3）
    AlarmRole role = AlarmRole::DST_ACTIVE;
};

// ============================================================
//  DependencyEntry — 端口依赖索引条目
// ============================================================

struct DependencyEntry {
    int32_t   fiber_id = 0;
    AlarmRole role     = AlarmRole::DST_ACTIVE;
};

// ============================================================
//  FiberTopologyInfo — Layer 1 解析结果
// ============================================================

struct FiberTopologyInfo {
    int32_t     fiber_id = 0;

    PortKey     src;             ///< 源端（board_id, port_id）
    PortKey     dst;             ///< 宿端（board_id, port_id）

    BoardType   src_board_type = BoardType::ACTIVE;
    BoardType   dst_board_type = BoardType::ACTIVE;

    SceneType   scene_type     = SceneType::SCENE_1;
    ScenarioCase scenario_case = ScenarioCase::CASE_0;

    /// 所有关联的对端（场景2时填充）
    std::vector<PeerInfo> peers;

    /// 主路对端（Port-2 对端 Board-B），场景2A/2B 有效
    std::optional<PeerInfo> primary_peer;

    /// 备路对端（Port-3 对端 Board-A2），仅场景2A 有效
    std::optional<PeerInfo> backup_peer;

    bool is_inter_ne = true;     ///< 是否网元间连纤
};

// ============================================================
//  ColorContext — 颜色计算上下文缓存
// ============================================================

struct ColorContext {
    FiberColor  color         = FiberColor::GREEN;
    SceneType   scene_type    = SceneType::SCENE_1;
    ScenarioCase scenario_case = ScenarioCase::CASE_0;

    int32_t     board_B       = 0;  ///< Port-2 对端单盘
    int32_t     board_A2      = 0;  ///< Port-3 对端单盘

    int64_t     last_update_ts = 0; ///< 最后更新 Unix 时间戳 (ms)
};

// ============================================================
//  AlarmTarget — Layer 2 告警查询目标
// ============================================================

struct AlarmTarget {
    int32_t   board_id  = 0;
    int32_t   port_id   = 1;   ///< 通常为 Port-1
    AlarmRole role      = AlarmRole::DST_ACTIVE;
};

// ============================================================
//  PerfTarget — Layer 2 性能查询目标
// ============================================================

struct PerfTarget {
    int32_t board_id = 0;
    int32_t port_id  = 1;
    bool    is_src   = true;   ///< true = 取 OOP, false = 取 IOP
};

// ============================================================
//  SpanlossPair — Layer 2 衰耗查询对
// ============================================================

struct SpanlossPair {
    int32_t src_board_id = 0;
    int32_t src_port_id  = 1;
    int32_t dst_board_id = 0;
    int32_t dst_port_id  = 1;
};

// ============================================================
//  PerfResult / SpanlossResult — Layer 3 查询结果
// ============================================================

struct PerfResult {
    int32_t fiber_id = 0;
    double  src_oop  = 0.0;
    double  dst_iop  = 0.0;
    bool    valid    = false;
    std::string error_message;
};

struct SpanlossResult {
    int32_t fiber_id  = 0;
    double  spanloss  = 0.0;
    bool    valid     = false;
    std::string error_message;
};

// ============================================================
//  ChangeRecord — 输出层写入记录
// ============================================================

struct ChangeRecord {
    int32_t    fiber_id = 0;
    FiberColor old_color = FiberColor::GREEN;
    FiberColor new_color = FiberColor::GREEN;
    SceneType  scene_type = SceneType::SCENE_1;
    ScenarioCase scenario_case = ScenarioCase::CASE_0;
    int64_t    timestamp_ms = 0;
};

// ============================================================
//  事件类型（CoalescingEventQueue 使用）
// ============================================================

enum class EventType : uint8_t {
    ALARM_EVENT  = 0,
    FIBER_EVENT  = 1,
    FULL_SYNC    = 2
};

const std::string AlarmLevelStr[] = {
    "ALARM_LEVEL_UNSPECIFIED",
    "CRITICAL",
    "MINOR"
};

struct QueueEvent {
    EventType   type = EventType::ALARM_EVENT;
    int32_t     board_id  = 0;
    int32_t     port_id   = 0;
    int32_t     fiber_id  = 0;
    int8_t      alarm_level = 0;
    bool        is_raise    = true;   ///< 告警产生 vs 告警消除
    bool        is_inter_ne = true;   ///< 连纤事件：是否网元间
    std::string raw_data;             ///< 原始事件序列化（用于日志）
};

// ============================================================
//  同步状态机
// ============================================================

enum class SyncState : uint8_t {
    STARTING   = 0,  ///< 启动中，gRPC 返回 UNAVAILABLE
    STREAMING  = 1,  ///< 流式接收中
    SYNCED     = 2,  ///< 全量同步完成，完全就绪
    RESYNCING  = 3   ///< 断线重连后重新同步中
};

// ============================================================
//  SmallVector<T, N> — 栈上存储优化的小容器
// ============================================================

template <typename T, size_t N = 2>
class SmallVector {
public:
    SmallVector() noexcept = default;

    void push_back(const T& val) {
        if (size_ < N) {
            stack_[size_++] = val;
        } else {
            if (overflow_.empty()) {
                overflow_.reserve(N);
            }
            overflow_.push_back(val);
            size_++;
        }
    }

    void clear() noexcept {
        size_ = 0;
        overflow_.clear();
    }

    size_t size() const noexcept { return size_; }
    bool   empty() const noexcept { return size_ == 0; }

    T& operator[](size_t idx) {
        return idx < N ? stack_[idx] : overflow_[idx - N];
    }
    const T& operator[](size_t idx) const {
        return idx < N ? stack_[idx] : overflow_[idx - N];
    }

    // 迭代器支持（简化版：转为连续数组遍历）
    class iterator {
    public:
        iterator(SmallVector* sv, size_t pos) : sv_(sv), pos_(pos) {}
        T& operator*() { return (*sv_)[pos_]; }
        iterator& operator++() { ++pos_; return *this; }
        bool operator!=(const iterator& o) const { return pos_ != o.pos_; }
    private:
        SmallVector* sv_;
        size_t pos_;
    };

    class const_iterator {
    public:
        const_iterator(const SmallVector* sv, size_t pos) : sv_(sv), pos_(pos) {}
        const T& operator*() const { return (*sv_)[pos_]; }
        const_iterator& operator++() { ++pos_; return *this; }
        bool operator!=(const const_iterator& o) const { return pos_ != o.pos_; }
    private:
        const SmallVector* sv_;
        size_t pos_;
    };

    iterator begin() { return iterator(this, 0); }
    iterator end()   { return iterator(this, size_); }
    const_iterator begin() const { return const_iterator(this, 0); }
    const_iterator end()   const { return const_iterator(this, size_); }

private:
    T              stack_[N]{};
    size_t         size_ = 0;
    std::vector<T> overflow_;
};

} // namespace fiber_maint
