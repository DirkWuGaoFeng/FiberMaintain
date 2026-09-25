#pragma once
/**
 * @file trend_page.h
 * @author FiberMaintain Team
 * @brief 统计趋势页：红/黄/彩色总数随时间变化曲线
 *
 * 设计意图：时间档位 1h/6h/24h/7d 一键切换 + 自定义区间，默认 24h；
 * 切换即重绘（项目前端规范要求图表随时间范围动态重绘）。
 */

#include <QWidget>
#include <QVector>
#include "models/fiber_models.h"

class ApiClient;
class QChartView;
class QDateTimeEdit;
class QPushButton;
class QLabel;

class TrendPage : public QWidget {
    Q_OBJECT
public:
    explicit TrendPage(ApiClient* api, QWidget* parent = nullptr);

    /// 页面首次可见时自动拉取一次
    void refresh();

private:
    void buildUi();
    void fetchRange(const QString& start, const QString& end);
    void applyPreset(int hours);
    void rebuildChart();

    ApiClient* api_;
    QVector<models::TrendPoint> points_;
    QChartView* chart_view_;
    QLabel* lbl_status_;
    QDateTimeEdit* edit_start_;
    QDateTimeEdit* edit_end_;
    QVector<QPushButton*> preset_btns_;   // 索引 0..3 = 1h/6h/24h/7d
    quint64 generation_ = 0;              // 防止旧响应覆盖新数据
};
