/**
 * @file server_probe.cpp
 * @author FiberMaintain Team
 * @brief 网关地址自动发现实现
 */

#include "util/server_probe.h"

#include "api/api_client.h"

#include <QProcess>

ServerProbe::ServerProbe(ApiClient* api, QObject* parent) : QObject(parent), api_(api) {}

void ServerProbe::probe(const QString& preferred) {
    candidates_.clear();
    if (!preferred.isEmpty() && !candidates_.contains(preferred))
        candidates_ << preferred;
    const QString local = QStringLiteral("http://localhost:8080");
    if (!candidates_.contains(local))
        candidates_ << local;
    index_ = 0;
    tryNext();
}

void ServerProbe::tryNext() {
    if (index_ >= candidates_.size()) {
        // 静态候选耗尽 → 进入 WSL IP 发现阶段
        startWslDiscovery();
        return;
    }
    const QString base = candidates_[index_++];
    api_->setBaseUrl(base);
    api_->getHealth([this, base](const QJsonObject& json, const QString& error) {
        if (error.isEmpty() && json.value("status").toString() == "ok") {
            emit probeFinished(true, base);
            return;
        }
        tryNext();
    });
}

void ServerProbe::startWslDiscovery() {
    if (wsl_proc_) return;   // 已在探测中
    wsl_proc_ = new QProcess(this);
    connect(wsl_proc_, &QProcess::finished, this, [this](int code) {
        QStringList urls;
        if (code == 0) {
            const QString out = QString::fromUtf8(wsl_proc_->readAllStandardOutput()).trimmed();
            for (const QString& ip : out.split(' ', Qt::SkipEmptyParts)) {
                if (ip.contains(':')) continue;   // 跳过 IPv6
                const QString url = QStringLiteral("http://%1:8080").arg(ip);
                if (!candidates_.contains(url)) urls << url;
            }
        }
        wsl_proc_->deleteLater();
        wsl_proc_ = nullptr;
        if (urls.isEmpty()) {
            emit probeFinished(false, QString());
            return;
        }
        candidates_ << urls;
        tryNext();
    });
    connect(wsl_proc_, &QProcess::errorOccurred, this, [this]() {
        wsl_proc_->deleteLater();
        wsl_proc_ = nullptr;
        emit probeFinished(false, QString());
    });
    wsl_proc_->start(QStringLiteral("wsl"), {QStringLiteral("-e"), QStringLiteral("hostname"), QStringLiteral("-I")});
}
