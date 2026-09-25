/**
 * @file color_grid_widget.cpp
 * @author FiberMaintain Team
 * @brief 光纤颜色方格视图实现
 */

#include "ui/color_grid_widget.h"

#include <QScrollArea>
#include <QPainter>
#include <QMouseEvent>
#include <QToolTip>
#include <QResizeEvent>

namespace {

/// 语义色：红=故障、黄=劣化、绿=正常、灰=未知
QColor colorOf(const QString& c) {
    if (c == "RED") return QColor(0xd9, 0x30, 0x26);
    if (c == "YELLOW") return QColor(0xe6, 0xa7, 0x00);
    if (c == "GREEN") return QColor(0x1f, 0x9e, 0x55);
    return QColor(0x90, 0x93, 0x99);
}

QString tipOf(const models::FiberRow& row) {
    return QStringLiteral("光纤 %1  [%2]\n%3:%4 → %5:%6  场景类型 %7")
        .arg(row.fiber_id).arg(row.color)
        .arg(row.src_board_id).arg(row.src_port_id)
        .arg(row.dst_board_id).arg(row.dst_port_id)
        .arg(row.scenario_type);
}

} // namespace

ColorGridWidget::ColorGridWidget(QWidget* parent) : QWidget(parent) {
    setMouseTracking(true);   // 无按键也接收 move 事件，用于 tooltip
    scroll_ = new QScrollArea(parent);
    scroll_->setWidget(this);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QFrame::NoFrame);
    setMinimumHeight(120);
}

void ColorGridWidget::setFibers(const QVector<models::FiberRow>& fibers) {
    fibers_ = fibers;
    relayout();
    update();
}

void ColorGridWidget::relayout() {
    const int pitch = cell_size_ + cell_gap_;
    cols_ = qMax(1, (width() - cell_gap_) / pitch);
    const int rows = (fibers_.size() + cols_ - 1) / cols_;
    const int h = rows * pitch + cell_gap_;
    if (height() != h) setFixedHeight(h);
}

QRect ColorGridWidget::cellRect(int index) const {
    const int pitch = cell_size_ + cell_gap_;
    const int x = cell_gap_ + (index % cols_) * pitch;
    const int y = cell_gap_ + (index / cols_) * pitch;
    return QRect(x, y, cell_size_, cell_size_);
}

int ColorGridWidget::cellAt(const QPoint& pos) const {
    const int pitch = cell_size_ + cell_gap_;
    const int col = (pos.x() - cell_gap_) / pitch;
    const int row = (pos.y() - cell_gap_) / pitch;
    if (col < 0 || row < 0 || col >= cols_) return -1;
    const int idx = row * cols_ + col;
    if (idx >= fibers_.size()) return -1;
    if (!cellRect(idx).contains(pos)) return -1;   // 命中间距不算
    return idx;
}

void ColorGridWidget::paintEvent(QPaintEvent*) {
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    for (int i = 0; i < fibers_.size(); ++i) {
        const QRect r = cellRect(i);
        p.setPen(Qt::NoPen);
        p.setBrush(colorOf(fibers_[i].color));
        p.drawRoundedRect(r, 3, 3);
    }
}

void ColorGridWidget::mousePressEvent(QMouseEvent* event) {
    const int idx = cellAt(event->pos());
    if (idx >= 0) emit fiberClicked(fibers_[idx].fiber_id);
}

bool ColorGridWidget::event(QEvent* e) {
    if (e->type() == QEvent::ToolTip) {
        auto* tip = static_cast<QHelpEvent*>(e);
        const int idx = cellAt(tip->pos());
        if (idx >= 0) {
            QToolTip::showText(tip->globalPos(), tipOf(fibers_[idx]), this);
            return true;
        }
        QToolTip::hideText();
    }
    return QWidget::event(e);
}
