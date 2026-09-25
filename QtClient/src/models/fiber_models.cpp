/**
 * @file fiber_models.cpp
 * @author FiberMaintain Team
 * @brief 数据模型解析实现
 */

#include "models/fiber_models.h"

namespace models {

int colorRank(const QString& color) {
    if (color == "RED") return 0;
    if (color == "YELLOW") return 1;
    if (color == "GREEN") return 2;
    return 3;
}

QVector<FiberRow> parseColoredFibers(const QJsonArray& fibers) {
    QVector<FiberRow> rows;
    rows.reserve(fibers.size());
    for (const auto& v : fibers) {
        const QJsonObject obj = v.toObject();
        const QJsonObject f = obj.value("fiber").toObject();
        FiberRow row;
        row.fiber_id     = f.value("fiber_id").toInt();
        row.src_board_id = f.value("src_board_id").toInt();
        row.src_port_id  = f.value("src_port_id").toInt();
        row.src_ne_id    = f.value("src_ne_id").toInt();
        row.dst_board_id = f.value("dst_board_id").toInt();
        row.dst_port_id  = f.value("dst_port_id").toInt();
        row.dst_ne_id    = f.value("dst_ne_id").toInt();
        row.color        = obj.value("color").toString("UNKNOWN");
        row.scenario_type = obj.value("scenario_type").toInt();
        rows.push_back(row);
    }
    return rows;
}

QVector<AlarmItem> parseAlarms(const QJsonArray& alarms) {
    QVector<AlarmItem> items;
    items.reserve(alarms.size());
    for (const auto& v : alarms) {
        const QJsonObject obj = v.toObject();
        AlarmItem item;
        item.board_id    = obj.value("board_id").toInt();
        item.port_id     = obj.value("port_id").toInt();
        item.fiber_id    = obj.value("fiber_id").toInt();
        item.alarm_level = obj.value("alarm_level").toString("UNSPECIFIED");
        item.raised_at   = obj.value("raised_at").toString();
        item.event       = obj.value("event").toString("ALARM_RAISED");
        items.push_back(item);
    }
    return items;
}

StatsData parseStats(const QJsonObject& obj) {
    StatsData s;
    s.total_fibers  = obj.value("total_fibers").toInt();
    s.red_count     = obj.value("red_count").toInt();
    s.yellow_count  = obj.value("yellow_count").toInt();
    s.green_count   = obj.value("green_count").toInt();
    s.active_alarms = obj.value("active_alarms").toInt();
    return s;
}

QVector<PerfRecord> parsePerfRecords(const QJsonArray& records) {
    QVector<PerfRecord> out;
    out.reserve(records.size());
    for (const auto& v : records) {
        const QJsonObject obj = v.toObject();
        PerfRecord r;
        r.recorded_at = obj.value("recorded_at").toString();
        r.src_oop     = obj.value("src_oop").toDouble();
        r.dst_iop     = obj.value("dst_iop").toDouble();
        out.push_back(r);
    }
    return out;
}

QVector<TrendPoint> parseTrendPoints(const QJsonArray& points) {
    QVector<TrendPoint> out;
    out.reserve(points.size());
    for (const auto& v : points) {
        const QJsonObject obj = v.toObject();
        TrendPoint p;
        p.timestamp     = obj.value("timestamp").toString();
        p.red_count     = obj.value("red_count").toInt();
        p.yellow_count  = obj.value("yellow_count").toInt();
        p.total_colored = obj.value("total_colored").toInt();
        out.push_back(p);
    }
    return out;
}

} // namespace models
