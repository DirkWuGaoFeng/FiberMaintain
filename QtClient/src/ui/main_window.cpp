/**
 * @file main_window.cpp
 * @author FiberMaintain Team
 * @brief 主窗口实现（连接编排 / 三段式同步 / 托盘提醒 / 状态栏）
 */

#include "ui/main_window.h"

#include "api/api_client.h"
#include "ws/ws_client.h"
#include "util/server_probe.h"
#include "ui/dashboard_page.h"
#include "ui/alarms_page.h"
#include "ui/trend_page.h"
#include "ui/detail_drawer.h"
#include "ui/settings_dialog.h"

#include <QListWidget>
#include <QStackedWidget>
#include <QHBoxLayout>
#include <QLabel>
#include <QStatusBar>
#include <QSystemTrayIcon>
#include <QMenu>
#include <QTimer>
#include <QDateTime>
#include <QApplication>
#include <QCloseEvent>
#include <QSettings>
#include <QPainter>
#include <QStyle>
#include <QPushButton>

namespace {

/// 状态圆点图标（代码内绘制，免二进制资源）
QIcon dotIcon(const QColor& c) {
    QPixmap pm(14, 14);
    pm.fill(Qt::transparent);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(Qt::NoPen);
    p.setBrush(c);
    p.drawEllipse(2, 2, 10, 10);
    return QIcon(pm);
}

/// 托盘图标：深色圆底 + 绿色光纤点
QIcon trayIcon() {
    QPixmap pm(64, 64);
    pm.fill(Qt::transparent);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(0x2b, 0x3a, 0x4a));
    p.drawEllipse(4, 4, 56, 56);
    p.setBrush(QColor(0x1f, 0x9e, 0x55));
    p.drawEllipse(20, 20, 24, 24);
    return QIcon(pm);
}

QString fmtJsonTime() {
    return QDateTime::currentDateTime().toString("HH:mm:ss");
}

} // namespace

MainWindow::MainWindow(QWidget* parent) : QMainWindow(parent) {
    setWindowTitle(QStringLiteral("光纤维护监控台"));
    resize(1400, 860);

    api_ = new ApiClient(this);
    ws_ = new WsClient(this);
    probe_ = new ServerProbe(api_, this);

    loadSettings();
    buildUi();
    connectClients();

    // 启动即探测：上次地址 → localhost → WSL IP；全部失败弹设置框
    probe_->probe(server_url_);
    health_timer_->start(10000);
}

MainWindow::~MainWindow() = default;

void MainWindow::buildUi() {
    // ── 左侧导航 ──
    nav_ = new QListWidget(this);
    nav_->setObjectName(QStringLiteral("navList"));
    nav_->setFixedWidth(150);
    nav_->addItem(QStringLiteral("大盘"));
    nav_->addItem(QStringLiteral("告警"));
    nav_->addItem(QStringLiteral("趋势"));

    stack_ = new QStackedWidget(this);
    dashboard_ = new DashboardPage(this);
    alarms_page_ = new AlarmsPage(api_, this);
    trend_page_ = new TrendPage(api_, this);
    stack_->addWidget(dashboard_);
    stack_->addWidget(alarms_page_);
    stack_->addWidget(trend_page_);

    drawer_ = new DetailDrawer(api_, this);
    drawer_->hide();

    connect(nav_, &QListWidget::currentRowChanged, stack_, &QStackedWidget::setCurrentIndex);
    connect(nav_, &QListWidget::currentRowChanged, this, [this](int row) {
        if (row == 2) trend_page_->refresh();   // 切到趋势页即刷新
    });

    auto* center = new QWidget(this);
    auto* center_lay = new QHBoxLayout(center);
    center_lay->setContentsMargins(0, 0, 0, 0);
    center_lay->setSpacing(0);
    center_lay->addWidget(stack_, 1);
    center_lay->addWidget(drawer_);
    setCentralWidget(center);

    // ── 状态栏 ──
    lbl_ws_ = new QLabel(QStringLiteral("WS: 未连接"), this);
    lbl_health_ = new QLabel(QStringLiteral("网关: -"), this);
    lbl_refresh_ = new QLabel(QStringLiteral("刷新: -"), this);
    lbl_alarms_ = new QLabel(QStringLiteral("活动告警: 0"), this);
    auto* btn_settings = new QPushButton(QStringLiteral("设置"), this);
    connect(btn_settings, &QPushButton::clicked, this, &MainWindow::onOpenSettings);
    statusBar()->addWidget(lbl_ws_);
    statusBar()->addWidget(lbl_health_);
    statusBar()->addPermanentWidget(lbl_refresh_);
    statusBar()->addPermanentWidget(lbl_alarms_);
    statusBar()->addPermanentWidget(btn_settings);

    // ── 系统托盘 ──
    tray_ = new QSystemTrayIcon(trayIcon(), this);
    auto* menu = new QMenu(this);
    menu->addAction(QStringLiteral("显示主窗口"), this, [this] { showNormal(); });
    menu->addSeparator();
    menu->addAction(QStringLiteral("退出"), qApp, &QApplication::quit);
    tray_->setContextMenu(menu);
    tray_->setToolTip(QStringLiteral("光纤维护监控台"));
    tray_->show();
    connect(tray_, &QSystemTrayIcon::activated, this, [this](QSystemTrayIcon::ActivationReason r) {
        if (r == QSystemTrayIcon::Trigger) { showNormal(); raise(); }
    });

    // 定时器：网关健康 10s；降级轮询 5s（仅 WS 断开时运行）
    health_timer_ = new QTimer(this);
    health_timer_->setInterval(10000);
    connect(health_timer_, &QTimer::timeout, this, &MainWindow::pollGatewayHealth);
    fallback_timer_ = new QTimer(this);
    fallback_timer_->setInterval(5000);
    connect(fallback_timer_, &QTimer::timeout, this, &MainWindow::loadDashboard);
}

void MainWindow::connectClients() {
    // 探测结果 → 应用地址；失败 → 打开设置
    connect(probe_, &ServerProbe::probeFinished, this, [this](bool ok, const QString& url) {
        if (ok) {
            applyServerUrl(url);
        } else {
            lbl_health_->setText(QStringLiteral("网关: 不可达"));
            lbl_health_->setPixmap(dotIcon(QColor(0xd9, 0x30, 0x26)).pixmap(12, 12));
            onOpenSettings();
        }
    });

    // WS 生命周期
    connect(ws_, &WsClient::connected, this, [this] {
        lbl_ws_->setText(QStringLiteral("WS: 已连接"));
        lbl_ws_->setPixmap(dotIcon(QColor(0x1f, 0x9e, 0x55)).pixmap(12, 12));
        stopFallbackPolling();
        loadDashboard();                    // 重连全量补偿
        alarms_page_->reloadFromRest();
    });
    connect(ws_, &WsClient::disconnected, this, [this] {
        lbl_ws_->setText(QStringLiteral("WS: 断开(重连中)"));
        lbl_ws_->setPixmap(dotIcon(QColor(0xd9, 0x30, 0x26)).pixmap(12, 12));
        startFallbackPolling();             // 降级 5s 轮询
    });

    // WS 事件分发
    connect(ws_, &WsClient::fiberColorChange, this, &MainWindow::onColorChange);
    connect(ws_, &WsClient::alarmEvent, this, &MainWindow::onAlarm);
    connect(ws_, &WsClient::fiberStats, this, [this](const QJsonObject& msg) {
        dashboard_->setStats(models::parseStats(msg.value("data").toObject()));
        last_refresh_ = fmtJsonTime();
        lbl_refresh_->setText(QStringLiteral("刷新: %1 (推送)").arg(last_refresh_));
    });
    connect(ws_, &WsClient::fiberLifecycleEvent, this, [this](const QJsonObject& msg) {
        const QString ev = msg.value("event").toString();
        if (ev == "FIBER_DELETED") {
            const int fid = msg.value("fiber_id").toInt();
            dashboard_->removeFiber(fid);
            fibers_by_id_.remove(fid);
        } else {
            loadDashboard();   // 新建光纤带完整拓扑信息，直接全量补偿
        }
    });

    // 大盘 → 详情抽屉
    connect(dashboard_, &DashboardPage::fiberClicked, this, [this](int fid) {
        const QString color = fibers_by_id_.contains(fid) ? fibers_by_id_[fid].color : QString();
        drawer_->showFiber(fid, color);
    });
    connect(dashboard_, &DashboardPage::refreshRequested, this, &MainWindow::loadDashboard);

    // 告警页 → 状态栏/托盘
    connect(alarms_page_, &AlarmsPage::activeCountChanged, this, [this](int count) {
        lbl_alarms_->setText(QStringLiteral("活动告警: %1").arg(count));
    });
    connect(alarms_page_, &AlarmsPage::signalCritical, this, [this](const models::AlarmItem& a) {
        notifyTray(QStringLiteral("CRITICAL 告警  %1:%2").arg(a.board_id).arg(a.port_id),
                   QStringLiteral("光纤 %1  级别 %2  %3")
                       .arg(a.fiber_id > 0 ? QString::number(a.fiber_id) : QStringLiteral("-"))
                       .arg(a.alarm_level, a.raised_at),
                   sound_on_critical_);
    });

    connect(api_, &ApiClient::requestError, this, [this](const QString& err) {
        statusBar()->showMessage(QStringLiteral("请求失败: %1").arg(err), 4000);
    });
}

void MainWindow::applyServerUrl(const QString& http_url) {
    if (http_url.isEmpty()) return;
    server_url_ = http_url;
    QString ws_url = http_url;
    ws_url.replace(QStringLiteral("http://"), QStringLiteral("ws://"));
    ws_url.replace(QStringLiteral(":8080"), QStringLiteral(":8081"));
    ws_url += QStringLiteral("/ws/v1/events");

    api_->setBaseUrl(http_url);
    ws_->setUrl(ws_url);
    ws_->start();
    saveSettings();
}

void MainWindow::loadDashboard() {
    // 全量环节：colored/all 建本地表 → 推给大盘与方格视图
    api_->getAllColoredFibers([this](const QJsonObject& json, const QString& error) {
        if (!error.isEmpty()) return;
        const auto rows = models::parseColoredFibers(json.value("fibers").toArray());
        fibers_by_id_.clear();
        for (const auto& r : rows) fibers_by_id_.insert(r.fiber_id, r);
        dashboard_->setFibers(rows);
        last_refresh_ = fmtJsonTime();
        lbl_refresh_->setText(QStringLiteral("刷新: %1%2")
                                  .arg(last_refresh_,
                                       ws_->isConnected() ? QStringLiteral(" (推送)") : QStringLiteral(" (轮询)")));
    });
    api_->getRealtimeStats([this](const QJsonObject& json, const QString& error) {
        if (!error.isEmpty()) return;
        dashboard_->setStats(models::parseStats(json));
    });
}

void MainWindow::startFallbackPolling() {
    if (!fallback_timer_->isActive()) fallback_timer_->start();
}

void MainWindow::stopFallbackPolling() {
    fallback_timer_->stop();
}

void MainWindow::onColorChange(const QJsonObject& msg) {
    const int fid = msg.value("fiber_id").toInt();
    const QString new_color = msg.value("new_color").toString();
    // 事件契约的 scene_type 与大盘 scenario_type 列同源（均映射 proto scene_type），
    // 取 scene_type 保证增量更新与全量 colored/all 的行语义一致
    const int scene_type = msg.value("scene_type").toInt();
    dashboard_->applyColorChange(fid, new_color, scene_type);
    if (fibers_by_id_.contains(fid)) {
        fibers_by_id_[fid].color = new_color;
        fibers_by_id_[fid].scenario_type = scene_type;
    }
    // 变红等同核心运维事件：托盘气泡（不含声音，与计划一致）
    if (new_color == "RED") {
        notifyTray(QStringLiteral("光纤变红"),
                   QStringLiteral("光纤 %1 颜色变为 RED（%2 → RED）")
                       .arg(fid).arg(msg.value("old_color").toString()),
                   false);
    }
}

void MainWindow::onAlarm(const QJsonObject& msg) {
    alarms_page_->onWsAlarm(msg);   // 提醒决策在 AlarmsPage::signalCritical 链路里
}

void MainWindow::notifyTray(const QString& title, const QString& body, bool sound) {
    if (tray_ && tray_->isSystemTrayAvailable())
        tray_->showMessage(title, body, QSystemTrayIcon::Information, 5000);
    if (sound) QApplication::beep();
    // 任务栏闪烁：激活并 raise 即可让系统任务栏按钮高亮
    showNormal();
    raise();
    activateWindow();
}

void MainWindow::pollGatewayHealth() {
    if (server_url_.isEmpty()) return;
    const auto t0 = QDateTime::currentMSecsSinceEpoch();
    api_->getHealth([this, t0](const QJsonObject& json, const QString& error) {
        const int ms = int(QDateTime::currentMSecsSinceEpoch() - t0);
        if (error.isEmpty() && json.value("status").toString() == "ok") {
            lbl_health_->setText(QStringLiteral("网关: 正常 %1ms").arg(ms));
            lbl_health_->setPixmap(dotIcon(QColor(0x1f, 0x9e, 0x55)).pixmap(12, 12));
        } else {
            lbl_health_->setText(QStringLiteral("网关: 不可达"));
            lbl_health_->setPixmap(dotIcon(QColor(0xd9, 0x30, 0x26)).pixmap(12, 12));
        }
    });
}

void MainWindow::onOpenSettings() {
    QString ws_url = api_->baseUrl();
    ws_url.replace(QStringLiteral("http://"), QStringLiteral("ws://"));
    ws_url.replace(QStringLiteral(":8080"), QStringLiteral(":8081"));
    ws_url += QStringLiteral("/ws/v1/events");

    SettingsDialog dlg(api_, ws_url, this);
    dlg.setChecked(sound_on_critical_);
    if (dlg.exec() == QDialog::Accepted) {
        sound_on_critical_ = dlg.soundEnabled();
        const QString url = dlg.serverUrl();
        if (!url.isEmpty() && url != api_->baseUrl()) {
            ws_->stop();
            applyServerUrl(url);
            probe_->probe(url);   // 校验新地址（失败会再次弹设置框）
        }
        saveSettings();
    }
}

void MainWindow::saveSettings() {
    QSettings settings(QStringLiteral("FiberMaintain"), QStringLiteral("FiberMonitorClient"));
    settings.setValue(QStringLiteral("serverUrl"), server_url_);
    settings.setValue(QStringLiteral("soundOnCritical"), sound_on_critical_);
}

void MainWindow::loadSettings() {
    QSettings settings(QStringLiteral("FiberMaintain"), QStringLiteral("FiberMonitorClient"));
    server_url_ = settings.value(QStringLiteral("serverUrl")).toString();
    sound_on_critical_ = settings.value(QStringLiteral("soundOnCritical"), true).toBool();
}

void MainWindow::closeEvent(QCloseEvent* event) {
    // 有托盘时关窗 = 隐藏到后台继续监控
    if (tray_ && tray_->isVisible()) {
        hide();
        tray_->showMessage(QStringLiteral("光纤维护监控台"),
                           QStringLiteral("已最小化到托盘，仍在后台监控"),
                           QSystemTrayIcon::Information, 3000);
        event->ignore();
    } else {
        ws_->stop();
        event->accept();
    }
}
