#pragma once
/**
 * @file main_window.h
 * @author FiberMaintain Team
 * @brief 主窗口：导航 + 页面栈 + 详情抽屉 + 状态栏 + 系统托盘
 *
 * 设计意图：主窗口是全客户端唯一的"连接编排者"——
 *   1) 启动后 ServerProbe 自动发现网关地址（QSettings 上次地址 → localhost → WSL IP）；
 *   2) REST baseUrl 与 WS url 同源派生（http→ws、端口 8080→8081）；
 *   3) 三段式颜色同步在此收口：连接成功全量拉取、WS 事件增量更新、
 *      WS 断开期间降级 5s 轮询；
 *   4) CRITICAL 告警与变红事件在此转成托盘气泡/声音/任务栏闪烁，
 *      页面层不接触系统通知（职责分离）。
 */

#include <QMainWindow>
#include <QVector>
#include <QHash>
#include <QJsonObject>
#include "models/fiber_models.h"

class ApiClient;
class WsClient;
class ServerProbe;
class DashboardPage;
class AlarmsPage;
class TrendPage;
class DetailDrawer;
class QListWidget;
class QStackedWidget;
class QLabel;
class QSystemTrayIcon;
class QTimer;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

protected:
    void closeEvent(QCloseEvent* event) override;   // 最小化到托盘

private:
    void buildUi();
    void connectClients();          // 接线 ApiClient / WsClient / ServerProbe
    void applyServerUrl(const QString& http_url);   // 同步 REST/WS 地址并持久化

    void loadDashboard();           // 全量：colored/all + realtime stats
    void startFallbackPolling();
    void stopFallbackPolling();

    void notifyTray(const QString& title, const QString& body, bool sound);
    void onColorChange(const QJsonObject& msg);
    void onAlarm(const QJsonObject& msg);
    void onOpenSettings();
    void pollGatewayHealth();
    void saveSettings();
    void loadSettings();

    // 基础设施
    ApiClient* api_;
    WsClient* ws_;
    ServerProbe* probe_;
    QTimer* health_timer_;          // 网关 /health 轮询（10s）
    QTimer* fallback_timer_;        // WS 断开期降级轮询（5s）
    QTimer* sync_timer_ = nullptr;  // 重连合并拉取的单发定时器

    // UI
    QListWidget* nav_;
    QStackedWidget* stack_;
    DashboardPage* dashboard_;
    AlarmsPage* alarms_page_;
    TrendPage* trend_page_;
    DetailDrawer* drawer_;
    QLabel* lbl_ws_;
    QLabel* lbl_health_;
    QLabel* lbl_refresh_;
    QLabel* lbl_alarms_;
    QSystemTrayIcon* tray_;

    // 设置项
    QString server_url_;
    bool sound_on_critical_ = true;

    // 本地颜色表（fiber_id → 行），供事件增量与抽屉取色
    QHash<int, models::FiberRow> fibers_by_id_;
    QString last_refresh_;
};
