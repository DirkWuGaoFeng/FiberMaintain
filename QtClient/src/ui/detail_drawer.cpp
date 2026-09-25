/**
 * @file detail_drawer.cpp
 * @author FiberMaintain Team
 * @brief 光纤详情抽屉实现
 */

#include "ui/detail_drawer.h"

#include "api/api_client.h"
#include "models/fiber_models.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QPushButton>
#include <QGroupBox>
#include <QDateTime>
#include <QtCharts/QChartView>
#include <QLineSeries>
#include <QCategoryAxis>
#include <QValueAxis>
#include <algorithm>

namespace {

/// 历史曲线默认窗口：最近 24 小时（与计划档位默认值一致）
QPair<QString, QString> last24h() {
    const QDateTime now = QDateTime::currentDateTime();
    return {now.addSecs(-24 * 3600).toString("yyyy-MM-dd HH:mm:ss"),
            now.toString("yyyy-MM-dd HH:mm:ss")};
}

} // namespace

DetailDrawer::DetailDrawer(ApiClient* api, QWidget* parent)
    : QFrame(parent), api_(api) {
    buildUi();
}

void DetailDrawer::buildUi() {
    setObjectName(QStringLiteral("detailDrawer"));
    setFixedWidth(380);
    setFrameShape(QFrame::StyledPanel);

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(12, 10, 12, 10);
    root->setSpacing(8);

    // ── 标题行 + 关闭按钮 ──
    auto* title_row = new QHBoxLayout;
    lbl_title_ = new QLabel(QStringLiteral("光纤详情"), this);
    lbl_title_->setStyleSheet(QStringLiteral("font-size:16px; font-weight:bold;"));
    auto* btn_close = new QPushButton(QStringLiteral("✕"), this);
    btn_close->setFixedSize(26, 26);
    connect(btn_close, &QPushButton::clicked, this, &DetailDrawer::closeDrawer);
    title_row->addWidget(lbl_title_);
    title_row->addStretch(1);
    title_row->addWidget(btn_close);
    root->addLayout(title_row);

    // ── 信息组 ──
    auto* grp_info = new QGroupBox(QStringLiteral("基础信息"), this);
    auto* lay_info = new QVBoxLayout(grp_info);
    lbl_info_ = new QLabel(QStringLiteral("-"), this);
    lbl_info_->setWordWrap(true);
    lay_info->addWidget(lbl_info_);
    root->addWidget(grp_info);

    auto* grp_perf = new QGroupBox(QStringLiteral("当前性能 / 跨损"), this);
    auto* lay_perf = new QVBoxLayout(grp_perf);
    lbl_perf_ = new QLabel(QStringLiteral("-"), this);
    lbl_perf_->setWordWrap(true);
    lbl_loss_ = new QLabel(QStringLiteral("-"), this);
    lay_perf->addWidget(lbl_perf_);
    lay_perf->addWidget(lbl_loss_);
    root->addWidget(grp_perf);

    auto* grp_scene = new QGroupBox(QStringLiteral("场景"), this);
    auto* lay_scene = new QVBoxLayout(grp_scene);
    lbl_scene_ = new QLabel(QStringLiteral("-"), this);
    lbl_scene_->setWordWrap(true);
    lay_scene->addWidget(lbl_scene_);
    root->addWidget(grp_scene);

    // ── 历史曲线 ──
    auto* grp_hist = new QGroupBox(QStringLiteral("近 24h 光功率历史"), this);
    auto* lay_hist = new QVBoxLayout(grp_hist);
    chart_view_ = new QChartView(this);
    chart_view_->setRenderHint(QPainter::Antialiasing);
    chart_view_->setMinimumHeight(220);
    lay_hist->addWidget(chart_view_);
    root->addWidget(grp_hist, 1);
}

void DetailDrawer::showFiber(int fiber_id, const QString& color) {
    ++generation_;
    fiber_id_ = fiber_id;
    color_ = color;
    snap_ = Snapshot();
    lbl_title_->setText(QStringLiteral("光纤 %1  [%2]").arg(fiber_id).arg(color));
    lbl_info_->setText(QStringLiteral("加载中…"));
    lbl_perf_->setText(QStringLiteral("加载中…"));
    lbl_loss_->setText(QStringLiteral("-"));
    lbl_scene_->setText(QStringLiteral("加载中…"));
    setVisible(true);
    fetchAll(fiber_id);
}

void DetailDrawer::closeDrawer() {
    ++generation_;   // 丢弃在途回调
    setVisible(false);
    emit closeRequested();
}

void DetailDrawer::fetchAll(int fiber_id) {
    const quint64 gen = generation_;

    // 基础信息
    api_->getFiberInfo(fiber_id, [this, gen](const QJsonObject& json, const QString& error) {
        if (gen != generation_ || !error.isEmpty()) return;
        const QJsonObject f = json.value("fiber").toObject();
        if (f.isEmpty()) { lbl_info_->setText(QStringLiteral("未找到该光纤")); return; }
        snap_.src = QStringLiteral("%1:%2").arg(f.value("src_board_id").toInt()).arg(f.value("src_port_id").toInt());
        snap_.dst = QStringLiteral("%1:%2").arg(f.value("dst_board_id").toInt()).arg(f.value("dst_port_id").toInt());
        snap_.ne  = QStringLiteral("%1 → %2").arg(f.value("src_ne_id").toInt()).arg(f.value("dst_ne_id").toInt());
        lbl_info_->setText(QStringLiteral("路径: %1 → %2\n网元: %3")
                               .arg(snap_.src, snap_.dst, snap_.ne));
    });

    // 当前性能
    api_->getFiberPerformance(fiber_id, [this, gen](const QJsonObject& json, const QString& error) {
        if (gen != generation_ || !error.isEmpty()) return;
        snap_.src_oop = json.value("src_oop").toDouble();
        snap_.dst_iop = json.value("dst_iop").toDouble();
        lbl_perf_->setText(QStringLiteral("发端光功率 (src_oop): %1 dBm\n收端光功率 (dst_iop): %2 dBm")
                               .arg(snap_.src_oop, 0, 'f', 2).arg(snap_.dst_iop, 0, 'f', 2));
    });

    // 跨损
    api_->getFiberSpanloss(fiber_id, [this, gen](const QJsonObject& json, const QString& error) {
        if (gen != generation_ || !error.isEmpty()) return;
        snap_.spanloss = json.value("spanloss").toDouble();
        lbl_loss_->setText(QStringLiteral("跨损 (spanloss): %1 dB").arg(snap_.spanloss, 0, 'f', 2));
    });

    // 场景
    api_->getFiberScene(fiber_id, [this, gen](const QJsonObject& json, const QString& error) {
        if (gen != generation_ || !error.isEmpty()) return;
        const QJsonObject scene = json.value("scene").toObject();
        if (scene.isEmpty()) { lbl_scene_->setText(QStringLiteral("无场景信息")); return; }
        lbl_scene_->setText(QStringLiteral("场景类型: %1\n站内部光纤: %2 条\n无源单盘: %3 块")
                                .arg(scene.value("scene_type").toInt())
                                .arg(scene.value("ne_internal_fibers").toArray().size())
                                .arg(scene.value("passive_boards").toArray().size()));
    });

    // 历史曲线
    const auto [st, et] = last24h();
    api_->getFiberHistory(fiber_id, st, et, [this, gen](const QJsonObject& json, const QString& error) {
        if (gen != generation_ || !error.isEmpty()) return;
        records_ = models::parsePerfRecords(json.value("records").toArray());
        rebuildChart();
    });
}

void DetailDrawer::rebuildChart() {
    auto* chart = new QChart;
    chart->legend()->setVisible(true);
    chart->legend()->setAlignment(Qt::AlignBottom);

    auto* series_oop = new QLineSeries;
    auto* series_iop = new QLineSeries;
    series_oop->setName(QStringLiteral("发端 OOP"));
    series_iop->setName(QStringLiteral("收端 IOP"));
    series_oop->setColor(QColor(0x1a, 0x6f, 0xb5));
    series_iop->setColor(QColor(0x1f, 0x9e, 0x55));

    const int n = records_.size();
    if (n == 0) {
        // 无采样：空图上挂提示文本，避免坐标轴无意义自mapping
        chart->setTitle(QStringLiteral("暂无历史数据"));
        chart_view_->setChart(chart);
        return;
    }

    const int step = qMax(1, n / 6);   // x 轴标签最多约 6 个，避免重叠
    auto* axis_x = new QCategoryAxis;
    auto* axis_y = new QValueAxis;
    double y_min = 1e30, y_max = -1e30;
    for (int i = 0; i < n; ++i) {
        const QDateTime dt = QDateTime::fromString(records_[i].recorded_at, "yyyy-MM-dd HH:mm:ss");
        const double x = dt.isValid() ? dt.toMSecsSinceEpoch() / 1000.0 : i;
        series_oop->append(x, records_[i].src_oop);
        series_iop->append(x, records_[i].dst_iop);
        y_min = std::min({y_min, records_[i].src_oop, records_[i].dst_iop});
        y_max = std::max({y_max, records_[i].src_oop, records_[i].dst_iop});
        if (i % step == 0 && dt.isValid())
            axis_x->append(dt.toString("MM-dd HH:mm"), x);
    }
    const double range = std::max(y_max - y_min, 1.0);
    axis_y->setRange(y_min - range * 0.1, y_max + range * 0.1);
    axis_y->setTitleText(QStringLiteral("dBm"));

    chart->addSeries(series_oop);
    chart->addSeries(series_iop);
    chart->addAxis(axis_x, Qt::AlignBottom);
    chart->addAxis(axis_y, Qt::AlignLeft);
    series_oop->attachAxis(axis_x);
    series_oop->attachAxis(axis_y);
    series_iop->attachAxis(axis_x);
    series_iop->attachAxis(axis_y);

    chart_view_->setChart(chart);
}
