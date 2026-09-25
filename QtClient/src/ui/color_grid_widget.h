#pragma once
/**
 * @file color_grid_widget.h
 * @author FiberMaintain Team
 * @brief 光纤颜色方格视图（大盘的图形化替代）
 *
 * 设计意图：每根光纤绘制为一个小色块，按状态色编码，一眼看清全网健康度；
 * 鼠标悬停显示 tooltip，点击进入详情。自绘 + 手动滚动条，避免 QML 依赖。
 */

#include <QWidget>
#include <QVector>
#include "models/fiber_models.h"

class QScrollArea;
class QMouseEvent;

class ColorGridWidget : public QWidget {
    Q_OBJECT
public:
    explicit ColorGridWidget(QWidget* parent = nullptr);

    /// 外层滚动容器（供大盘页放入布局）
    QScrollArea* scrollArea() const { return scroll_; }

    void setFibers(const QVector<models::FiberRow>& fibers);

signals:
    void fiberClicked(int fiber_id);

protected:
    void paintEvent(QPaintEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    bool event(QEvent* e) override;   // 处理 ToolTip 事件

private:
    QRect cellRect(int index) const;
    int cellAt(const QPoint& pos) const;
    void relayout();

    QScrollArea* scroll_;
    QVector<models::FiberRow> fibers_;
    int cell_size_ = 26;       // 色块边长（含间距）
    int cell_gap_ = 4;
    int cols_ = 1;
};
