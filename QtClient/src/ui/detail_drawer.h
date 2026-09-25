#pragma once
/**
 * @file detail_drawer.h
 * @author FiberMaintain Team
 * @brief 光纤详情抽屉（主窗口右侧嵌入，可折叠）
 *
 * 设计意图：点击大盘行/方格后按需懒加载 4 个接口（基础信息、当前性能、
 * 跨损、场景 + 24h 历史曲线），全部异步回填；generation 计数保证快速切换
 * 光纤时旧响应不会覆盖新数据。
 */

#include <QFrame>
#include <QString>
#include <QVector>
#include "models/fiber_models.h"

class ApiClient;
class QLabel;
class QChartView;

class DetailDrawer : public QFrame {
    Q_OBJECT
public:
    explicit DetailDrawer(ApiClient* api, QWidget* parent = nullptr);

    /// 展示指定光纤详情（懒加载全部子数据）
    void showFiber(int fiber_id, const QString& color);
    void closeDrawer();

signals:
    void closeRequested();

private:
    struct Snapshot {
        QString src, dst, ne;
        double src_oop = 0.0;
        double dst_iop = 0.0;
        double spanloss = 0.0;
    };

    void buildUi();
    void fetchAll(int fiber_id);
    void rebuildChart();

    ApiClient* api_;
    quint64 generation_ = 0;      // 每次 showFiber 递增，回调中校验
    int fiber_id_ = 0;
    QString color_;
    Snapshot snap_;
    QVector<models::PerfRecord> records_;   // 近 24h 历史采样

    QLabel* lbl_title_;
    QLabel* lbl_info_;
    QLabel* lbl_perf_;
    QLabel* lbl_loss_;
    QLabel* lbl_scene_;
    QChartView* chart_view_;
};
