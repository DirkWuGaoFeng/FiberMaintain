#pragma once
/**
 * @file ws_client.h
 * @author FiberMaintain Team
 * @brief 网关 WebSocket 事件推送客户端
 *
 * 设计意图：
 * - 断线后指数退避自动重连（1s → 2s → 4s ... 上限 30s），重连成功后由上层
 *   通过 connected 信号触发全量补偿拉取（三段式同步的"重连全量"环节）；
 * - 每 10 秒发送 {"action":"ping"} 保活，与网关 process_message 约定一致；
 * - 收到的 JSON 按 type 字段分发为强类型信号，UI 层不接触原始报文。
 */

#include <QObject>
#include <QJsonObject>
#include <QString>

class QWebSocket;
class QTimer;

class WsClient : public QObject {
    Q_OBJECT
public:
    explicit WsClient(QObject* parent = nullptr);

    void setUrl(const QString& url);    // 例：ws://172.22.181.152:8081/ws/v1/events
    void start();                       // 开始连接并保持自动重连
    void stop();                        // 主动停止（退出时调用，不再重连）
    bool isConnected() const { return connected_; }

signals:
    void connected();
    void disconnected();
    /// 告警事件：event=ALARM_RAISED/ALARM_CLEARED
    void alarmEvent(const QJsonObject& msg);
    /// 光纤创建/删除事件
    void fiberLifecycleEvent(const QJsonObject& msg);
    /// 光纤颜色迁移事件（fiber_color_change）
    void fiberColorChange(const QJsonObject& msg);
    /// 周期统计（fiber_stats）
    void fiberStats(const QJsonObject& msg);

private slots:
    void onConnected();
    void onDisconnected();
    void onTextMessage(const QString& text);
    void onReconnectTimeout();
    void onPingTimeout();

private:
    void scheduleReconnect();

    QWebSocket* ws_;
    QTimer* reconnect_timer_;
    QTimer* ping_timer_;
    QString url_;
    int retry_seconds_ = 1;        // 指数退避状态
    bool started_ = false;         // start() 之后才允许自动重连
    bool connected_ = false;
};
