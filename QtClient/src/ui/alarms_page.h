#pragma once
/**
 * @file alarms_page.h
 * @author FiberMaintain Team
 * @brief 告警面板：当前活动告警 + 事件流 + 级别过滤
 *
 * 设计意图：活动告警表以 (board,port,level) 为主键，由 REST 全量快照与
 * WS 增量事件共同维护（RAISED 插入 / CLEARED 删除），保证两者最终一致；
 * 事件流表仅保留最近 200 条供回溯。CRITICAL 产生时发 signalCritical 供
 * 主窗口做托盘+声音提醒，面板自身不接触系统托盘（职责分离）。
 */

#include <QWidget>
#include <QAbstractTableModel>
#include <QHash>
#include <QSet>
#include "models/fiber_models.h"

class ApiClient;
class QTableView;
class QComboBox;
class QLabel;
class QStandardItemModel;

/// 活动告警模型：列 = 板卡/端口/光纤/级别/产生时间
class ActiveAlarmModel : public QAbstractTableModel {
    Q_OBJECT
public:
    enum Column { ColBoard = 0, ColPort, ColFiber, ColLevel, ColRaisedAt, ColCount };
    enum Roles { LevelRole = Qt::UserRole + 1 };

    explicit ActiveAlarmModel(QObject* parent = nullptr);

    void setActive(const QVector<models::AlarmItem>& alarms);   // REST 快照全量替换
    void raise(const models::AlarmItem& alarm);                 // WS 增量
    void clear(const models::AlarmItem& alarm);                 // WS 增量

    int rowCount(const QModelIndex& parent = QModelIndex()) const override;
    int columnCount(const QModelIndex& parent = QModelIndex()) const override;
    QVariant data(const QModelIndex& index, int role) const override;
    QVariant headerData(int section, Qt::Orientation orientation, int role) const override;

private:
    static QString keyOf(const models::AlarmItem& a);

    QVector<models::AlarmItem> items_;
    QHash<QString, int> index_;   // key → items_ 下标
};

class AlarmsPage : public QWidget {
    Q_OBJECT
public:
    explicit AlarmsPage(ApiClient* api, QWidget* parent = nullptr);

    /// WS alarm 消息入口（主窗口直接转发原始 JSON）
    void onWsAlarm(const QJsonObject& msg);
    /// REST 快照刷新（启动、重连、降级轮询、手动刷新共用）
    void reloadFromRest();
    int activeCount() const { return model_.rowCount(); }

signals:
    /// CRITICAL 告警产生（托盘气泡 + 声音 + 任务栏闪烁由主窗口处理）
    void signalCritical(const models::AlarmItem& alarm);
    /// 活动告警数变化 → 状态栏
    void activeCountChanged(int count);

private:
    void buildUi();

    ApiClient* api_;
    ActiveAlarmModel model_;
    QTableView* table_active_;
    QTableView* table_events_;
    QStandardItemModel* events_model_;
    QComboBox* combo_filter_;
    QLabel* lbl_count_;
    int events_dropped_ = 0;
};
