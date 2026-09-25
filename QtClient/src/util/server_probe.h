#pragma once
/**
 * @file server_probe.h
 * @author FiberMaintain Team
 * @brief 网关地址自动发现
 *
 * 设计意图：后端跑在 WSL，其 IP 每次重启可能变化，且 Windows 侧不能用
 * localhost 访问（项目已知坑）。探测顺序：
 *   1) QSettings 保存的上次成功地址 → 2) http://localhost:8080
 *   → 3) `wsl -e hostname -I` 输出的各 IP 逐个尝试。
 * 逐个异步 GET /health，命中即发 probeFinished(true)；全部失败发 false。
 */

#include <QObject>
#include <QStringList>

class ApiClient;
class QProcess;

class ServerProbe : public QObject {
    Q_OBJECT
public:
    explicit ServerProbe(ApiClient* api, QObject* parent = nullptr);

    /// 启动探测。preferred 为 QSettings 中的上次地址（可为空）
    void probe(const QString& preferred);

signals:
    /// ok=true 时 url 为命中的 baseUrl；ok=false 表示全部候选失败
    void probeFinished(bool ok, const QString& url);

private:
    void tryNext();
    void startWslDiscovery();

    static QStringList wslCandidateUrls();

    ApiClient* api_;
    QStringList candidates_;
    int index_ = 0;
    QProcess* wsl_proc_ = nullptr;
};
