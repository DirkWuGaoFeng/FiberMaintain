#pragma once
/**
 * @file api_client.h
 * @author FiberMaintain Team
 * @brief api_gateway REST 接口封装（全异步）
 *
 * 设计意图：
 * - 所有请求通过 QNetworkAccessManager 异步发出，以回调返回解析后的 JSON，
 *   UI 层不接触 QNetworkReply，错误统一归一化为 errorText；
 * - 超时固定 5 秒，避免 WSL 网络抖动时 UI 悬挂；
 * - baseUrl 可在设置对话框中热切换（WSL IP 变化场景）。
 */

#include <QObject>
#include <QString>
#include <QUrl>
#include <QJsonObject>
#include <QJsonArray>
#include <functional>

class QNetworkAccessManager;

/// REST 回调：成功时 json 有效、error 为空
using JsonCallback = std::function<void(const QJsonObject& json, const QString& error)>;

class ApiClient : public QObject {
    Q_OBJECT
public:
    explicit ApiClient(QObject* parent = nullptr);

    void setBaseUrl(const QString& url);           // 例：http://172.22.181.152:8080
    QString baseUrl() const { return base_url_; }

    // ── 通用 GET ──
    void get(const QString& path, const QUrlQuery& query, JsonCallback cb);

    // ── 业务接口（路径与网关 http_server.cpp 一一对应） ──
    void getHealth(JsonCallback cb);                                   // GET /health
    void getAllColoredFibers(JsonCallback cb);                         // GET /api/v1/fibers/colored/all
    void getRealtimeStats(JsonCallback cb);                            // GET /api/v1/fibers/stats/realtime
    void getStatsTrend(const QString& start, const QString& end, JsonCallback cb); // GET /api/v1/fibers/stats/trend
    void getCurrentAlarms(JsonCallback cb);                            // GET /api/v1/alarms/current
    void getFiberInfo(int fiber_id, JsonCallback cb);                  // GET /api/v1/topology/fibers/{id}
    void getFiberPerformance(int fiber_id, JsonCallback cb);           // GET /api/v1/fibers/{id}/performance
    void getFiberSpanloss(int fiber_id, JsonCallback cb);              // GET /api/v1/fibers/{id}/spanloss
    void getFiberHistory(int fiber_id, const QString& start, const QString& end,
                         JsonCallback cb);                             // GET /api/v1/fibers/{id}/performance/history
    void getFiberScene(int fiber_id, JsonCallback cb);                 // GET /api/v1/topology/fibers/{id}/scene

signals:
    /// 任意请求失败（供状态栏提示，不区分具体请求）
    void requestError(const QString& error);

private:
    QNetworkAccessManager* nam_;
    QString base_url_ = "http://localhost:8080";
};
