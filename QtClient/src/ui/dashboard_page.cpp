/**
 * @file dashboard_page.cpp
 * @author FiberMaintain Team
 * @brief 大盘页实现
 */

#include "ui/dashboard_page.h"

#include "ui/color_grid_widget.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QTableView>
#include <QLineEdit>
#include <QLabel>
#include <QPushButton>
#include <QButtonGroup>
#include <QHeaderView>
#include <QSortFilterProxyModel>
#include <QTimer>
#include <QItemSelectionModel>
#include <QScrollArea>

// ═══════════════════════════ FiberTableModel ═══════════════════════════

FiberTableModel::FiberTableModel(QObject* parent) : QAbstractTableModel(parent) {}

void FiberTableModel::sortRows() {
    std::stable_sort(rows_.begin(), rows_.end(), [](const models::FiberRow& a, const models::FiberRow& b) {
        const int ra = models::colorRank(a.color), rb = models::colorRank(b.color);
        if (ra != rb) return ra < rb;
        return a.fiber_id < b.fiber_id;
    });
}

void FiberTableModel::setFibers(QVector<models::FiberRow> fibers) {
    beginResetModel();
    rows_ = std::move(fibers);
    flash_until_.clear();
    sortRows();
    endResetModel();
}

int FiberTableModel::fiberIndex(int fiber_id) const {
    for (int i = 0; i < rows_.size(); ++i)
        if (rows_[i].fiber_id == fiber_id) return i;
    return -1;
}

const models::FiberRow* FiberTableModel::fiberAt(int row_index) const {
    if (row_index < 0 || row_index >= rows_.size()) return nullptr;
    return &rows_[row_index];
}

bool FiberTableModel::applyColorChange(int fiber_id, const QString& new_color, int scenario_type) {
    const int idx = fiberIndex(fiber_id);
    if (idx < 0) return false;
    rows_[idx].color = new_color;
    rows_[idx].scenario_type = scenario_type;
    flash_until_[fiber_id] = QDateTime::currentDateTime().addMSecs(900);
    emit dataChanged(index(idx, 0), index(idx, columnCount() - 1));
    // 闪烁到期后恢复原样式并重新排序（红置顶）
    QTimer::singleShot(1000, this, [this, fiber_id]() {
        flash_until_.remove(fiber_id);
        const int from = fiberIndex(fiber_id);
        if (from < 0) return;
        QVector<models::FiberRow> sorted = rows_;
        sortRows();
        const int to = fiberIndex(fiber_id);
        if (sorted != rows_) {
            beginResetModel();
            endResetModel();   // 顺序变化：整表复位，代理过滤器量小可接受
            Q_UNUSED(to);
        } else {
            emit dataChanged(index(from, 0), index(from, columnCount() - 1));
        }
    });
    return true;
}

bool FiberTableModel::removeFiber(int fiber_id) {
    const int idx = fiberIndex(fiber_id);
    if (idx < 0) return false;
    beginRemoveRows(QModelIndex(), idx, idx);
    rows_.remove(idx);
    endRemoveRows();
    return true;
}

int FiberTableModel::rowCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : rows_.size();
}

int FiberTableModel::columnCount(const QModelIndex& parent) const {
    return parent.isValid() ? 0 : ColCount;
}

QVariant FiberTableModel::data(const QModelIndex& index, int role) const {
    if (!index.isValid() || index.row() >= rows_.size()) return {};
    const models::FiberRow& row = rows_[index.row()];

    if (role == Qt::DisplayRole) {
        switch (index.column()) {
        case ColFiberId:   return row.fiber_id;
        case ColColor:     return row.color;
        case ColSrc:       return QStringLiteral("%1:%2").arg(row.src_board_id).arg(row.src_port_id);
        case ColDst:       return QStringLiteral("%1:%2").arg(row.dst_board_id).arg(row.dst_port_id);
        case ColScenario:  return row.scenario_type;
        }
        return {};
    }
    if (role == Qt::TextAlignmentRole)
        return int(index.column() == ColColor ? Qt::AlignCenter : Qt::AlignVCenter | Qt::AlignLeft);
    if (role == FiberIdRole) return row.fiber_id;
    if (role == ColorRole)   return row.color;
    if (role == Qt::BackgroundRole) {
        // 闪烁高亮：颜色刚变化的行短暂标黄
        auto it = flash_until_.constFind(row.fiber_id);
        if (it != flash_until_.constEnd() && it.value() > QDateTime::currentDateTime())
            return QColor(0xff, 0xf3, 0xcd);
        if (index.column() == ColColor) {
            if (row.color == "RED")    return QColor(0xfd, 0xe4, 0xe2);
            if (row.color == "YELLOW") return QColor(0xfa, 0xec, 0xc8);
            if (row.color == "GREEN")  return QColor(0xe6, 0xf4, 0xea);
        }
        return {};
    }
    if (role == Qt::ForegroundRole && index.column() == ColColor) {
        if (row.color == "RED")    return QColor(0xd9, 0x30, 0x26);
        if (row.color == "YELLOW") return QColor(0x9c, 0x6e, 0x00);
        if (row.color == "GREEN")  return QColor(0x1f, 0x9e, 0x55);
    }
    return {};
}

QVariant FiberTableModel::headerData(int section, Qt::Orientation orientation, int role) const {
    if (orientation != Qt::Horizontal || role != Qt::DisplayRole) return {};
    switch (section) {
    case ColFiberId:  return QStringLiteral("光纤 ID");
    case ColColor:    return QStringLiteral("颜色");
    case ColSrc:      return QStringLiteral("起点(盘:口)");
    case ColDst:      return QStringLiteral("终点(盘:口)");
    case ColScenario: return QStringLiteral("场景类型");
    }
    return {};
}

// ═══════════════════════════ DashboardPage ═══════════════════════════

namespace {

/// 创建一张统计卡片，返回值标签用于更新数字
QLabel* makeStatCard(QHBoxLayout* row_lay, const QString& title, const QString& value_style) {
    auto* frame = new QFrame;
    frame->setObjectName(QStringLiteral("statCard"));
    auto* lay = new QVBoxLayout(frame);
    lay->setContentsMargins(14, 8, 14, 8);
    auto* value = new QLabel(QStringLiteral("0"));
    value->setObjectName(value_style);
    auto* name = new QLabel(title);
    name->setObjectName(QStringLiteral("statTitle"));
    lay->addWidget(value);
    lay->addWidget(name);
    row_lay->addWidget(frame);
    return value;
}

/// 过滤代理：任意列包含匹配
/// 自存过滤词而非依赖 filterFixedString（Qt6.10 已移除该 getter，
/// 且 setFilterFixedString 会对模式做正则转义，不适合直接做 contains 比对）
class RowFilterProxy : public QSortFilterProxyModel {
public:
    using QSortFilterProxyModel::QSortFilterProxyModel;
    void setFilterText(const QString& text) { filter_text_ = text; invalidateFilter(); }
protected:
    bool filterAcceptsRow(int sourceRow, const QModelIndex&) const override {
        auto* m = sourceModel();
        if (filter_text_.isEmpty()) return true;
        for (int c = 0; c < m->columnCount(); ++c) {
            if (m->index(sourceRow, c).data(Qt::DisplayRole).toString()
                    .contains(filter_text_, Qt::CaseInsensitive))
                return true;
        }
        return false;
    }
private:
    QString filter_text_;
};

} // namespace

DashboardPage::DashboardPage(QWidget* parent) : QWidget(parent), model_(new FiberTableModel(this)) {
    buildUi();
}

void DashboardPage::buildUi() {
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(12, 12, 12, 12);
    root->setSpacing(10);

    // ── 统计卡片行 ──
    auto* stats_row = new QHBoxLayout;
    stats_row->setSpacing(10);
    lbl_total_  = makeStatCard(stats_row, QStringLiteral("光纤总数"), QStringLiteral("statValue"));
    lbl_red_    = makeStatCard(stats_row, QStringLiteral("红色(故障)"), QStringLiteral("statValueRed"));
    lbl_yellow_ = makeStatCard(stats_row, QStringLiteral("黄色(劣化)"), QStringLiteral("statValueYellow"));
    lbl_green_  = makeStatCard(stats_row, QStringLiteral("绿色(正常)"), QStringLiteral("statValueGreen"));
    lbl_alarms_ = makeStatCard(stats_row, QStringLiteral("活动告警"), QStringLiteral("statValueRed"));
    root->addLayout(stats_row);

    // ── 工具行：过滤 + 视图切换 ──
    auto* tool_row = new QHBoxLayout;
    edit_filter_ = new QLineEdit(this);
    edit_filter_->setPlaceholderText(QStringLiteral("按 光纤ID / 盘:口 过滤…"));
    edit_filter_->setFixedWidth(240);
    auto* btn_table = new QPushButton(QStringLiteral("表格"), this);
    auto* btn_grid = new QPushButton(QStringLiteral("方格视图"), this);
    for (auto* b : {btn_table, btn_grid}) {
        b->setCheckable(true);
        b->setObjectName(QStringLiteral("rangeBtn"));
    }
    btn_table->setChecked(true);
    auto* grp = new QButtonGroup(this);
    grp->setExclusive(true);
    grp->addButton(btn_table, 0);
    grp->addButton(btn_grid, 1);
    tool_row->addWidget(edit_filter_);
    tool_row->addStretch(1);
    tool_row->addWidget(btn_table);
    tool_row->addWidget(btn_grid);
    root->addLayout(tool_row);

    // ── 内容栈：表格 / 方格 ──
    auto* proxy = new RowFilterProxy(this);
    proxy->setSourceModel(model_);

    table_ = new QTableView(this);
    table_->setModel(proxy);
    table_->setSortingEnabled(false);   // 模型内部已按红>黄>绿排序
    table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    table_->setSelectionMode(QAbstractItemView::SingleSelection);
    table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    table_->verticalHeader()->setVisible(false);
    table_->horizontalHeader()->setStretchLastSection(true);
    table_->horizontalHeader()->setSectionResizeMode(QHeaderView::Interactive);
    table_->setColumnWidth(FiberTableModel::ColFiberId, 90);
    table_->setColumnWidth(FiberTableModel::ColColor, 90);
    table_->setColumnWidth(FiberTableModel::ColSrc, 130);
    table_->setColumnWidth(FiberTableModel::ColDst, 130);

    grid_ = new ColorGridWidget(nullptr);
    grid_container_ = grid_->scrollArea();
    grid_container_->setParent(this);
    grid_container_->hide();

    auto* stack_lay = new QVBoxLayout;
    stack_lay->setContentsMargins(0, 0, 0, 0);
    stack_lay->addWidget(table_);
    stack_lay->addWidget(grid_container_);
    root->addLayout(stack_lay, 1);

    // ── 信号接线 ──
    connect(edit_filter_, &QLineEdit::textChanged, this, [proxy](const QString& text) {
        proxy->setFilterText(text.trimmed());
    });
    connect(table_, &QTableView::clicked, this, [this](const QModelIndex& idx) {
        const int fid = idx.siblingAtColumn(FiberTableModel::ColFiberId).data(FiberTableModel::FiberIdRole).toInt();
        if (fid > 0) emit fiberClicked(fid);
    });
    connect(grid_, &ColorGridWidget::fiberClicked, this, &DashboardPage::fiberClicked);
    connect(grp, &QButtonGroup::idClicked, this, [this, btn_table, btn_grid](int id) {
        const bool table_mode = (id == 0);
        if (table_mode) btn_table->setChecked(true); else btn_grid->setChecked(true);
        table_->setVisible(table_mode);
        grid_container_->setVisible(!table_mode);
    });
}

void DashboardPage::setFibers(const QVector<models::FiberRow>& fibers) {
    model_->setFibers(fibers);
    grid_->setFibers(fibers);
    current_count_ = fibers.size();
}

void DashboardPage::applyColorChange(int fiber_id, const QString& new_color, int scenario_type) {
    if (!model_->applyColorChange(fiber_id, new_color, scenario_type)) {
        // 本地不存在该光纤（新建场景等）→ 请求上层做一次全量补偿
        emit refreshRequested();
        return;
    }
    // 方格视图无增删改接口，整体重建（600 级色块开销可忽略）
    QVector<models::FiberRow> all;
    all.reserve(model_->rowCount());
    for (int i = 0; i < model_->rowCount(); ++i)
        if (const auto* row = model_->fiberAt(i)) all.append(*row);
    grid_->setFibers(all);
}

void DashboardPage::removeFiber(int fiber_id) {
    model_->removeFiber(fiber_id);
}

void DashboardPage::setStats(const models::StatsData& stats) {
    lbl_total_->setNum(stats.total_fibers);
    lbl_red_->setNum(stats.red_count);
    lbl_yellow_->setNum(stats.yellow_count);
    lbl_green_->setNum(stats.green_count);
    lbl_alarms_->setNum(stats.active_alarms);
}
