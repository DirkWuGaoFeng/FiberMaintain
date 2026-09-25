#pragma once
/**
 * @file dashboard_page.h
 * @author FiberMaintain Team
 * @brief 大盘页：统计卡片 + 彩色光纤表格 / 方格视图
 *
 * 设计意图：表格使用 QAbstractTableModel 直连内存行数据，全量刷新与
 * 单行增量更新（WS 颜色事件）都只触发局部 dataChanged，600+ 光纤无压力；
 * 颜色事件到达时目标行做一次性黄色闪烁高亮，提示变化位置。
 */

#include <QWidget>
#include <QAbstractTableModel>
#include <QVector>
#include <QHash>
#include <QDateTime>
#include "models/fiber_models.h"

class QLabel;
class QTableView;
class QLineEdit;
class QButtonGroup;
class ColorGridWidget;
class QTimer;

/// 光纤列表格模型：列 = 光纤ID/颜色/起点/终点/场景类型
class FiberTableModel : public QAbstractTableModel {
    Q_OBJECT
public:
    enum Column { ColFiberId = 0, ColColor, ColSrc, ColDst, ColScenario, ColCount };
    enum Roles { FiberIdRole = Qt::UserRole + 1, ColorRole };

    explicit FiberTableModel(QObject* parent = nullptr);

    void setFibers(QVector<models::FiberRow> fibers);
    /// 增量改色；返回是否命中。flash 标记该行需闪烁提示
    bool applyColorChange(int fiber_id, const QString& new_color, int scenario_type);
    bool removeFiber(int fiber_id);

    int fiberIndex(int fiber_id) const;    // 有序查找（按 fiber_id）
    const models::FiberRow* fiberAt(int row_index) const;

    int columnCount(const QModelIndex& parent = QModelIndex()) const override;
    int rowCount(const QModelIndex& parent = QModelIndex()) const override;
    QVariant data(const QModelIndex& index, int role) const override;
    QVariant headerData(int section, Qt::Orientation orientation, int role) const override;

private:
    void sortRows();   // 红>黄>绿，同级按 fiber_id 升序

    QVector<models::FiberRow> rows_;
    QHash<int, QDateTime> flash_until_;   // fiber_id → 闪烁截止时间戳
};

class DashboardPage : public QWidget {
    Q_OBJECT
public:
    explicit DashboardPage(QWidget* parent = nullptr);

    /// 全量刷新（三段式同步的全量环节）
    void setFibers(const QVector<models::FiberRow>& fibers);
    /// WS 增量颜色事件
    void applyColorChange(int fiber_id, const QString& new_color, int scenario_type);
    /// WS 光纤删除事件
    void removeFiber(int fiber_id);
    void setStats(const models::StatsData& stats);

signals:
    void fiberClicked(int fiber_id);
    /// 增量事件命中不了本地数据时，请求上层全量刷新
    void refreshRequested();

private:
    void buildUi();
    void applyFilter();
    void flashCell(int fiber_id);

    FiberTableModel* model_;
    QTableView* table_;
    ColorGridWidget* grid_;
    QWidget* grid_container_;
    QLineEdit* edit_filter_;
    QLabel* lbl_total_;
    QLabel* lbl_red_;
    QLabel* lbl_yellow_;
    QLabel* lbl_green_;
    QLabel* lbl_alarms_;
    int current_count_ = 0;
};
