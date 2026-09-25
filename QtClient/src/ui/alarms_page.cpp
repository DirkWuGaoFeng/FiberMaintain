/**
 * @file alarms_page.cpp
 * @author FiberMaintain Team
 * @brief 告警面板实现
 */

#include "ui/alarms_page.h"

#include "api/api_client.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QTableView>
#include <QComboBox>
#include <QLabel>
#include <QPushButton>
#include <QHeaderView>
#include <QSortFilterProxyModel>
#include <QStandardItemModel>

// ═══════════════════════════ ActiveAlarmModel ═══════════════════════════

ActiveAlarmModel::ActiveAlarmModel(QObject* parent) : QAbstractTableModel(parent) {}

QString ActiveAlarmModel::keyOf(const models::AlarmItem& a) {
    return QStringLiteral("%1:%2:%3").arg(a.board_id).arg(a.port_id).arg(a.alarm_level);
}

void ActiveAlarmModel::setActive(const QVector<models::AlarmItem>& alarms) {
    beginResetModel();
    items_ = alarms;
    index_.clear();
    for (int i = 0; i < items_.size(); ++i)
        index_.insert(keyOf(items_[i]), i);
    endResetModel();
}

void ActiveAlarmModel::raise(const models::AlarmItem& alarm) {
    const QString key = keyOf(alarm);
    if (index_.contains(key)) {           // 重复 RAISED：就地更新时间
        const int row = index_.value(key);
        items_[row] = alarm;
        emit dataChanged(index(row, 0), index(row, ColCount - 1));
        return;
    }
    beginInsertRows(QModelIndex(), 0, 0); // 新告警置顶
    items_.prepend(alarm);
    for (auto it = index_.begin(); it != index_.end(); ++it) it.value() += 1;
    index_.insert(key, 0);
    endInsertRows();
}

void ActiveAlarmModel::clear(const models::AlarmItem& alarm) {
    const QString key = keyOf(alarm);
    if (!index_.contains(key)) return;
    const int row = index_.value(key);
    beginRemoveRows(QModelIndex(), row, row);
    items_.remove(row);
    index_.remove(key);
    for (auto it = index_.begin(); it != index_.end(); ++it) {
        if (it.value() > row) it.value() -= 1;
    }
    endRemoveRows();
}

int ActiveAlarmModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : items_.size();
}

int ActiveAlarmModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : ColCount;
}

QVariant ActiveAlarmModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid() || index.row() >= items_.size()) return {};
    const models::AlarmItem& a = items_[index.row()];
    if (role == Qt::DisplayRole) {
        switch (index.column()) {
        case ColBoard:    return a.board_id;
        case ColPort:     return a.port_id;
        case ColFiber:    return a.fiber_id > 0 ? QVariant(a.fiber_id) : QVariant(QStringLiteral("-"));
        case ColLevel:    return a.alarm_level;
        case ColRaisedAt: return a.raised_at;
        }
        return {};
    }
    if (role == LevelRole) return a.alarm_level;
    if (role == Qt::BackgroundRole && index.column() == ColLevel) {
        if (a.alarm_level == "CRITICAL") return QColor(0xfd, 0xe4, 0xe2);
        if (a.alarm_level == "MINOR")    return QColor(0xfa, 0xec, 0xc8);
    }
    if (role == Qt::ForegroundRole && index.column() == ColLevel) {
        if (a.alarm_level == "CRITICAL") return QColor(0xd9, 0x30, 0x26);
        if (a.alarm_level == "MINOR")    return QColor(0x9c, 0x6e, 0x00);
    }
    return {};
}

QVariant ActiveAlarmModel::headerData(int section, Qt::Orientation orientation, int role) const {
    if (orientation != Qt::Horizontal || role != Qt::DisplayRole) return {};
    switch (section) {
    case ColBoard:    return QStringLiteral("板卡");
    case ColPort:     return QStringLiteral("端口");
    case ColFiber:    return QStringLiteral("光纤");
    case ColLevel:    return QStringLiteral("级别");
    case ColRaisedAt: return QStringLiteral("产生时间");
    }
    return {};
}

// ═══════════════════════════ AlarmsPage ═══════════════════════════

namespace {

/// 级别过滤代理（按 LevelRole 精确匹配）
class LevelFilterProxy : public QSortFilterProxyModel {
public:
    using QSortFilterProxyModel::QSortFilterProxyModel;
    void setFilterText(const QString& text) { filter_text_ = text; invalidateFilter(); }
protected:
    bool filterAcceptsRow(int sourceRow, const QModelIndex&) const override {
        if (filter_text_.isEmpty()) return true;
        return sourceModel()->index(sourceRow, ActiveAlarmModel::ColLevel)
                   .data(ActiveAlarmModel::LevelRole).toString() == filter_text_;
    }
private:
    QString filter_text_;
};

models::AlarmItem alarmFromWs(const QJsonObject& msg) {
    models::AlarmItem a;
    a.board_id    = msg.value("board_id").toInt();
    a.port_id     = msg.value("port_id").toInt();
    a.fiber_id    = msg.value("fiber_id").toInt();
    a.alarm_level = msg.value("alarm_level").toString("UNSPECIFIED");
    a.raised_at   = msg.value("timestamp").toString();
    a.event       = msg.value("event").toString();
    return a;
}

} // namespace

AlarmsPage::AlarmsPage(ApiClient* api, QWidget* parent) : QWidget(parent), api_(api) {
    buildUi();
}

void AlarmsPage::buildUi() {
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(12, 12, 12, 12);
    root->setSpacing(8);

    // ── 工具行 ──
    auto* tool = new QHBoxLayout;
    combo_filter_ = new QComboBox(this);
    combo_filter_->addItems({QStringLiteral("全部级别"), QStringLiteral("CRITICAL"), QStringLiteral("MINOR")});
    lbl_count_ = new QLabel(QStringLiteral("活动告警: 0"), this);
    auto* btn_reload = new QPushButton(QStringLiteral("刷新"), this);
    connect(btn_reload, &QPushButton::clicked, this, &AlarmsPage::reloadFromRest);
    tool->addWidget(combo_filter_);
    tool->addWidget(lbl_count_);
    tool->addStretch(1);
    tool->addWidget(btn_reload);
    root->addLayout(tool);

    // ── 活动告警表 ──
    auto* proxy = new LevelFilterProxy(this);
    proxy->setSourceModel(&model_);
    table_active_ = new QTableView(this);
    table_active_->setModel(proxy);
    table_active_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_active_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_active_->verticalHeader()->setVisible(false);
    table_active_->horizontalHeader()->setStretchLastSection(true);
    root->addWidget(new QLabel(QStringLiteral("<b>当前活动告警</b>"), this));
    root->addWidget(table_active_, 3);

    // ── 事件流表（最近 200 条） ──
    events_model_ = new QStandardItemModel(0, 5, this);
    events_model_->setHorizontalHeaderLabels(
        {QStringLiteral("时间"), QStringLiteral("事件"), QStringLiteral("板:口"),
         QStringLiteral("光纤"), QStringLiteral("级别")});
    table_events_ = new QTableView(this);
    table_events_->setModel(events_model_);
    table_events_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_events_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_events_->verticalHeader()->setVisible(false);
    table_events_->horizontalHeader()->setStretchLastSection(true);
    root->addWidget(new QLabel(QStringLiteral("<b>告警事件流</b>（本次会话，最多 200 条）"), this));
    root->addWidget(table_events_, 2);

    connect(combo_filter_, &QComboBox::currentTextChanged, this, [proxy](const QString& text) {
        proxy->setFilterText(text.startsWith(QStringLiteral("全部")) ? QString() : text);
    });
}

void AlarmsPage::reloadFromRest() {
    api_->getCurrentAlarms([this](const QJsonObject& json, const QString& error) {
        if (!error.isEmpty()) return;   // requestError 信号已在状态栏体现
        model_.setActive(models::parseAlarms(json.value("alarms").toArray()));
        emit activeCountChanged(model_.rowCount());
    });
}

void AlarmsPage::onWsAlarm(const QJsonObject& msg) {
    const models::AlarmItem alarm = alarmFromWs(msg);

    // 事件流：插到第 0 行，超上限丢弃最旧
    QList<QStandardItem*> row;
    row << new QStandardItem(alarm.raised_at)
        << new QStandardItem(alarm.event == "ALARM_CLEARED" ? QStringLiteral("清除") : QStringLiteral("产生"))
        << new QStandardItem(QStringLiteral("%1:%2").arg(alarm.board_id).arg(alarm.port_id))
        << new QStandardItem(alarm.fiber_id > 0 ? QString::number(alarm.fiber_id) : QStringLiteral("-"))
        << new QStandardItem(alarm.alarm_level);
    events_model_->insertRow(0, row);
    while (events_model_->rowCount() > 200) {
        events_model_->removeRow(events_model_->rowCount() - 1);
        ++events_dropped_;
    }

    // 活动表增量维护
    if (alarm.event == "ALARM_CLEARED")
        model_.clear(alarm);
    else
        model_.raise(alarm);
    emit activeCountChanged(model_.rowCount());

    if (alarm.event != "ALARM_CLEARED" && alarm.alarm_level == "CRITICAL")
        emit signalCritical(alarm);
}
