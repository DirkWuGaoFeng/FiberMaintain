/**
 * @file api_client.cpp
 * @author FiberMaintain Team
 * @brief api_gateway REST 接口封装实现
 */

#include "api/api_client.h"

#include <QNetworkAccessManager>
#include <QNetworkRequest>
#include <QNetworkReply>
#include <QUrlQuery>
#include <QJsonDocument>
#include <QTimer>

ApiClient::ApiClient(QObject* parent) : QObject(parent), nam_(new QNetworkAccessManager(this)) {}

void ApiClient::setBaseUrl(const QString& url) {
    base_url_ = url;
    while (base_url_.endsWith('/')) base_url_.chop(1);
}

void ApiClient::get(const QString& path, const QUrlQuery& query, JsonCallback cb) {
    QUrl url(base_url_ + path);
    url.setQuery(query);
    QNetworkRequest req(url);
    req.setTransferTimeout(5000);   // 5 秒超时，防止 WSL 网络悬挂

    QNetworkReply* reply = nam_->get(req);
    connect(reply, &QNetworkReply::finished, this, [this, reply, url, cb]() {
        reply->deleteLater();
        const int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
        const QByteArray body = reply->readAll();
        if (reply->error() != QNetworkReply::NoError && code != 200) {
            QString err = QStringLiteral("%1 (HTTP %2)").arg(reply->errorString()).arg(code);
            emit requestError(err);
            if (cb) cb(QJsonObject(), err);
            return;
        }
        QJsonParseError perr;
        const QJsonDocument doc = QJsonDocument::fromJson(body, &perr);
        if (perr.error != QJsonParseError::NoError || !doc.isObject()) {
            QString err = QStringLiteral("JSON 解析失败: %1").arg(perr.errorString());
            emit requestError(err);
            if (cb) cb(QJsonObject(), err);
            return;
        }
        if (cb) cb(doc.object(), QString());
    });
}

void ApiClient::getHealth(JsonCallback cb) {
    get("/health", QUrlQuery(), std::move(cb));
}

void ApiClient::getAllColoredFibers(JsonCallback cb) {
    get("/api/v1/fibers/colored/all", QUrlQuery(), std::move(cb));
}

void ApiClient::getRealtimeStats(JsonCallback cb) {
    get("/api/v1/fibers/stats/realtime", QUrlQuery(), std::move(cb));
}

void ApiClient::getStatsTrend(const QString& start, const QString& end, JsonCallback cb) {
    QUrlQuery q;
    if (!start.isEmpty()) q.addQueryItem("start_time", start);
    if (!end.isEmpty()) q.addQueryItem("end_time", end);
    get("/api/v1/fibers/stats/trend", q, std::move(cb));
}

void ApiClient::getCurrentAlarms(JsonCallback cb) {
    // 不带 board_id/port_id 时网关返回全部当前告警
    get("/api/v1/alarms/current", QUrlQuery(), std::move(cb));
}

void ApiClient::getFiberInfo(int fiber_id, JsonCallback cb) {
    get(QStringLiteral("/api/v1/topology/fibers/%1").arg(fiber_id), QUrlQuery(), std::move(cb));
}

void ApiClient::getFiberPerformance(int fiber_id, JsonCallback cb) {
    get(QStringLiteral("/api/v1/fibers/%1/performance").arg(fiber_id), QUrlQuery(), std::move(cb));
}

void ApiClient::getFiberSpanloss(int fiber_id, JsonCallback cb) {
    get(QStringLiteral("/api/v1/fibers/%1/spanloss").arg(fiber_id), QUrlQuery(), std::move(cb));
}

void ApiClient::getFiberHistory(int fiber_id, const QString& start, const QString& end, JsonCallback cb) {
    QUrlQuery q;
    if (!start.isEmpty()) q.addQueryItem("start_time", start);
    if (!end.isEmpty()) q.addQueryItem("end_time", end);
    get(QStringLiteral("/api/v1/fibers/%1/performance/history").arg(fiber_id), q, std::move(cb));
}

void ApiClient::getFiberScene(int fiber_id, JsonCallback cb) {
    get(QStringLiteral("/api/v1/topology/fibers/%1/scene").arg(fiber_id), QUrlQuery(), std::move(cb));
}
