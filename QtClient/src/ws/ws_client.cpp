/**
 * @file ws_client.cpp
 * @author FiberMaintain Team
 * @brief 网关 WebSocket 事件推送客户端实现
 */

#include "ws/ws_client.h"

#include <QWebSocket>
#include <QTimer>
#include <QJsonDocument>
#include <QJsonObject>

namespace {
constexpr int kPingIntervalMs = 10000;   // 保活间隔
constexpr int kRetryMaxSeconds = 30;     // 指数退避上限
}

WsClient::WsClient(QObject* parent) : QObject(parent) {
    ws_ = new QWebSocket(QString(), QWebSocketProtocol::VersionLatest, this);
    reconnect_timer_ = new QTimer(this);
    reconnect_timer_->setSingleShot(true);
    ping_timer_ = new QTimer(this);

    connect(ws_, &QWebSocket::connected, this, &WsClient::onConnected);
    connect(ws_, &QWebSocket::disconnected, this, &WsClient::onDisconnected);
    connect(ws_, &QWebSocket::textMessageReceived, this, &WsClient::onTextMessage);
    connect(reconnect_timer_, &QTimer::timeout, this, &WsClient::onReconnectTimeout);
    connect(ping_timer_, &QTimer::timeout, this, &WsClient::onPingTimeout);
}

void WsClient::setUrl(const QString& url) {
    if (url_ == url) return;
    url_ = url;
    // URL 变化后重新计退避并立即尝试连接
    retry_seconds_ = 1;
    if (started_) {
        ws_->abort();
        onDisconnected();
        onReconnectTimeout();
    }
}

void WsClient::start() {
    if (started_) return;
    started_ = true;
    ws_->open(QUrl(url_));
}

void WsClient::stop() {
    started_ = false;
    reconnect_timer_->stop();
    ping_timer_->stop();
    ws_->close();
}

void WsClient::onConnected() {
    connected_ = true;
    retry_seconds_ = 1;   // 连接成功即复位退避
    ping_timer_->start(kPingIntervalMs);
    emit connected();
}

void WsClient::onDisconnected() {
    const bool was = connected_;
    connected_ = false;
    ping_timer_->stop();
    if (was) emit disconnected();
    if (started_) scheduleReconnect();
}

void WsClient::onTextMessage(const QString& text) {
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(text.toUtf8(), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) return;
    const QJsonObject obj = doc.object();
    const QString type = obj.value("type").toString();
    if (type == "alarm") {
        emit alarmEvent(obj);
    } else if (type == "fiber_color") {
        emit fiberLifecycleEvent(obj);
    } else if (type == "fiber_color_change") {
        emit fiberColorChange(obj);
    } else if (type == "fiber_stats") {
        emit fiberStats(obj);
    }
    // pong 与其他未知类型直接忽略
}

void WsClient::onReconnectTimeout() {
    if (!started_ || connected_) return;
    ws_->open(QUrl(url_));
}

void WsClient::onPingTimeout() {
    if (connected_) ws_->sendTextMessage(QStringLiteral("{\"action\": \"ping\"}"));
}

void WsClient::scheduleReconnect() {
    reconnect_timer_->start(retry_seconds_ * 1000);
    retry_seconds_ = qMin(retry_seconds_ * 2, kRetryMaxSeconds);
}
