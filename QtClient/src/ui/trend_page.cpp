/**
 * @file trend_page.cpp
 * @author FiberMaintain Team
 * @brief 统计趋势页实现
 */

#include "ui/trend_page.h"

#include "api/api_client.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QDateTimeEdit>
#include <QCalendarWidget>
#include <QPushButton>
#include <QLabel>
#include <QButtonGroup>
#include <QDateTime>
#include <QtCharts/QChartView>
#include <QLineSeries>
#include <QCategoryAxis>
#include <QValueAxis>
#include <algorithm>

namespace {
constexpr const char* kTimeFormat = "yyyy-MM-dd HH:mm:ss";   // 网关时间参数格式
}

TrendPage::TrendPage(ApiClient* api, QWidget* parent) : QWidget(parent), api_(api) {
    buildUi();
}

void TrendPage::buildUi() {
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(12, 12, 12, 12);
    root->setSpacing(10);

    // ── 时间档位行 ──
    auto* preset_row = new QHBoxLayout;
    const QStringList labels{QStringLiteral("1 小时"), QStringLiteral("6 小时"),
                             QStringLiteral("24 小时"), QStringLiteral("7 天"), QStringLiteral("自定义")};
    for (int i = 0; i < labels.size(); ++i) {
        auto* btn = new QPushButton(labels[i], this);
        btn->setCheckable(true);
        btn->setObjectName(QStringLiteral("rangeBtn"));
        preset_btns_.append(btn);
        preset_row->addWidget(btn);
    }
    preset_row->addStretch(1);
    root->addLayout(preset_row);

    // ── 自定义区间行 ──
    auto* custom_row = new QHBoxLayout;
    edit_start_ = new QDateTimeEdit(QDateTime::currentDateTime().addSecs(-24 * 3600), this);
    edit_end_   = new QDateTimeEdit(QDateTime::currentDateTime(), this);
    for (auto* edit : {edit_start_, edit_end_}) {
        edit->setDisplayFormat(kTimeFormat);
        edit->setCalendarPopup(true);
    }
    auto* btn_apply = new QPushButton(QStringLiteral("应用"), this);
    custom_row->addWidget(new QLabel(QStringLiteral("起:"), this));
    custom_row->addWidget(edit_start_);
    custom_row->addWidget(new QLabel(QStringLiteral("止:"), this));
    custom_row->addWidget(edit_end_);
    custom_row->addWidget(btn_apply);
    custom_row->addStretch(1);
    lbl_status_ = new QLabel(this);
    custom_row->addWidget(lbl_status_);
    root->addLayout(custom_row);

    chart_view_ = new QChartView(this);
    chart_view_->setRenderHint(QPainter::Antialiasing);
    root->addWidget(chart_view_, 1);

    // ── 接线 ──
    connect(preset_btns_[0], &QPushButton::clicked, this, [this] { applyPreset(1); });
    connect(preset_btns_[1], &QPushButton::clicked, this, [this] { applyPreset(6); });
    connect(preset_btns_[2], &QPushButton::clicked, this, [this] { applyPreset(24); });
    connect(preset_btns_[3], &QPushButton::clicked, this, [this] { applyPreset(24 * 7); });
    connect(preset_btns_[4], &QPushButton::clicked, this, [this] {
        for (auto* b : preset_btns_) b->setChecked(false);
        preset_btns_[4]->setChecked(true);
        fetchRange(edit_start_->dateTime().toString(kTimeFormat),
                   edit_end_->dateTime().toString(kTimeFormat));
    });
    connect(btn_apply, &QPushButton::clicked, this, [this] { preset_btns_[4]->click(); });

    preset_btns_[2]->click();   // 默认 24h，同时完成首次拉取
}

void TrendPage::refresh() {
    fetchRange(edit_start_->dateTime().toString(kTimeFormat),
               edit_end_->dateTime().toString(kTimeFormat));
}

void TrendPage::applyPreset(int hours) {
    const QDateTime now = QDateTime::currentDateTime();
    edit_start_->setDateTime(now.addSecs(-hours * 3600));
    edit_end_->setDateTime(now);
    for (auto* b : preset_btns_) b->setChecked(false);
    const int idx = hours == 1 ? 0 : hours == 6 ? 1 : hours == 24 ? 2 : 3;
    preset_btns_[idx]->setChecked(true);
    fetchRange(edit_start_->dateTime().toString(kTimeFormat),
               edit_end_->dateTime().toString(kTimeFormat));
}

void TrendPage::fetchRange(const QString& start, const QString& end) {
    ++generation_;
    const quint64 gen = generation_;
    lbl_status_->setText(QStringLiteral("加载中…"));
    api_->getStatsTrend(start, end, [this, gen, start, end](const QJsonObject& json, const QString& error) {
        if (gen != generation_) return;
        if (!error.isEmpty()) {
            lbl_status_->setText(QStringLiteral("加载失败: %1").arg(error));
            return;
        }
        points_ = models::parseTrendPoints(json.value("points").toArray());
        lbl_status_->setText(QStringLiteral("%1 ~ %2  共 %3 个采样点")
                                 .arg(start, end).arg(points_.size()));
        rebuildChart();
    });
}

void TrendPage::rebuildChart() {
    auto* chart = new QChart;
    chart->legend()->setVisible(true);
    chart->legend()->setAlignment(Qt::AlignBottom);

    if (points_.isEmpty()) {
        chart->setTitle(QStringLiteral("所选时间范围内无趋势数据"));
        chart_view_->setChart(chart);
        return;
    }

    auto* s_red = new QLineSeries;
    auto* s_yellow = new QLineSeries;
    auto* s_total = new QLineSeries;
    s_red->setName(QStringLiteral("红色"));
    s_yellow->setName(QStringLiteral("黄色"));
    s_total->setName(QStringLiteral("彩色总数"));
    s_red->setColor(QColor(0xd9, 0x30, 0x26));
    s_yellow->setColor(QColor(0xe6, 0xa7, 0x00));
    s_total->setColor(QColor(0x1a, 0x6f, 0xb5));
    s_total->setPen(QPen(QColor(0x1a, 0x6f, 0xb5), 2, Qt::DashLine));

    const int n = points_.size();
    const int step = qMax(1, n / 8);
    auto* axis_x = new QCategoryAxis;
    auto* axis_y = new QValueAxis;
    int y_max = 1;
    for (int i = 0; i < n; ++i) {
        s_red->append(i, points_[i].red_count);
        s_yellow->append(i, points_[i].yellow_count);
        s_total->append(i, points_[i].total_colored);
        y_max = std::max({y_max, points_[i].red_count, points_[i].yellow_count, points_[i].total_colored});
        if (i % step == 0)
            axis_x->append(QDateTime::fromString(points_[i].timestamp, kTimeFormat)
                               .toString("MM-dd HH:mm"), i);
    }
    axis_y->setRange(0, y_max * 1.15);
    axis_y->setTitleText(QStringLiteral("数量"));

    chart->addSeries(s_red);
    chart->addSeries(s_yellow);
    chart->addSeries(s_total);
    chart->addAxis(axis_x, Qt::AlignBottom);
    chart->addAxis(axis_y, Qt::AlignLeft);
    for (auto* s : {s_red, s_yellow, s_total}) {
        s->attachAxis(axis_x);
        s->attachAxis(axis_y);
    }

    chart_view_->setChart(chart);
}
