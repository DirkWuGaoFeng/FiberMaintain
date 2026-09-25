#pragma once
/**
 * @file fiber_models.h
 * @author FiberMaintain Team
 * @brief 客户端数据模型与 JSON 解析辅助
 *
 * 设计意图：模型结构与 api_gateway REST/WS 的 JSON 契约一一对应，
 * 解析函数集中在此处，UI 层只消费强类型结构体，字段变更时只需改这一层。
 */

#include <QString>
#include <QVector>
#include <QJsonObject>
#include <QJsonArray>

namespace models {

/// 光纤行：对应 GET /api/v1/fibers/colored/all 的单个元素
struct FiberRow {
    int fiber_id = 0;
    int src_board_id = 0;
    int src_port_id = 0;
    int src_ne_id = 0;
    int dst_board_id = 0;
    int dst_port_id = 0;
    int dst_ne_id = 0;
    QString color;          // GREEN / RED / YELLOW
    int scenario_type = 0;  // 网关字段名为 scenario_type（对应 proto scene_type）

    // 供 QVector<FiberRow> 的 ==/!= 使用（大盘增量刷新前后比对排序是否变化）
    bool operator==(const FiberRow& o) const {
        return fiber_id == o.fiber_id && color == o.color &&
               scenario_type == o.scenario_type &&
               src_board_id == o.src_board_id && src_port_id == o.src_port_id &&
               dst_board_id == o.dst_board_id && dst_port_id == o.dst_port_id;
    }
};

/// 告警记录：对应 GET /api/v1/alarms/current 元素与 WS alarm 消息
struct AlarmItem {
    int board_id = 0;
    int port_id = 0;
    int fiber_id = 0;       // 仅 WS 消息携带
    QString alarm_level;    // CRITICAL / MINOR
    QString raised_at;
    QString event;          // ALARM_RAISED / ALARM_CLEARED（仅 WS）
};

/// 实时统计：对应 GET /api/v1/fibers/stats/realtime 与 WS fiber_stats
struct StatsData {
    int total_fibers = 0;
    int red_count = 0;
    int yellow_count = 0;
    int green_count = 0;
    int active_alarms = 0;
};

/// 性能历史采样点：对应 GET /api/v1/fibers/{id}/performance/history 记录
struct PerfRecord {
    QString recorded_at;
    double src_oop = 0.0;
    double dst_iop = 0.0;
};

/// 大盘趋势采样点：对应 GET /api/v1/fibers/stats/trend 的 points
struct TrendPoint {
    QString timestamp;
    int red_count = 0;
    int yellow_count = 0;
    int total_colored = 0;
};

/// 大盘颜色排序权重：红色置顶，其次黄色，其余绿色在后
int colorRank(const QString& color);

/// 解析 colored/all 响应
QVector<FiberRow> parseColoredFibers(const QJsonArray& fibers);

/// 解析 alarms/current 响应
QVector<AlarmItem> parseAlarms(const QJsonArray& alarms);

/// 解析 stats/realtime 或 WS fiber_stats 的 data 对象
StatsData parseStats(const QJsonObject& obj);

/// 解析性能历史 records 数组
QVector<PerfRecord> parsePerfRecords(const QJsonArray& records);

/// 解析趋势 points 数组
QVector<TrendPoint> parseTrendPoints(const QJsonArray& points);

} // namespace models
