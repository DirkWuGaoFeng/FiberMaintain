/**
 * @file settings_dialog.cpp
 * @author FiberMaintain Team
 * @brief 连接与提醒设置对话框实现
 */

#include "ui/settings_dialog.h"

#include "api/api_client.h"

#include <QFormLayout>
#include <QLineEdit>
#include <QCheckBox>
#include <QLabel>
#include <QPushButton>
#include <QDialogButtonBox>
#include <QVBoxLayout>
#include <QMessageBox>

SettingsDialog::SettingsDialog(ApiClient* api, const QString& wsUrl, QWidget* parent)
    : QDialog(parent), api_(api), ws_url_(wsUrl) {
    setWindowTitle(QStringLiteral("设置"));
    setMinimumWidth(420);

    edit_url_ = new QLineEdit(api->baseUrl(), this);
    edit_url_->setPlaceholderText(QStringLiteral("http://172.x.x.x:8080"));
    chk_sound_ = new QCheckBox(QStringLiteral("CRITICAL 告警声音提醒"), this);
    lbl_result_ = new QLabel(this);

    auto* form = new QFormLayout;
    form->addRow(QStringLiteral("网关地址:"), edit_url_);
    form->addRow(QStringLiteral("提醒:"), chk_sound_);

    auto* btn_test = new QPushButton(QStringLiteral("测试连接"), this);
    connect(btn_test, &QPushButton::clicked, this, &SettingsDialog::onTestConnection);

    auto* buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons, &QDialogButtonBox::accepted, this, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, this, &QDialog::reject);

    auto* test_row = new QHBoxLayout;
    test_row->addWidget(btn_test);
    test_row->addWidget(lbl_result_, 1);

    auto* root = new QVBoxLayout(this);
    root->addLayout(form);
    root->addLayout(test_row);
    root->addWidget(buttons);
}

QString SettingsDialog::serverUrl() const {
    QString url = edit_url_->text().trimmed();
    while (url.endsWith('/')) url.chop(1);
    return url;
}

bool SettingsDialog::soundEnabled() const {
    return chk_sound_->isChecked();
}

void SettingsDialog::setChecked(bool sound_on) {
    chk_sound_->setChecked(sound_on);
}

void SettingsDialog::onTestConnection() {
    QString url = serverUrl();
    if (url.isEmpty()) {
        lbl_result_->setText(QStringLiteral("地址为空"));
        return;
    }
    // 用候选地址临时发一次 /health，不改变客户端当前配置
    auto* probeApi = new ApiClient(this);
    probeApi->setBaseUrl(url);
    probeApi->getHealth([this, probeApi](const QJsonObject& json, const QString& error) {
        if (error.isEmpty() && json.value("status").toString() == "ok") {
            lbl_result_->setText(QStringLiteral("连接成功"));
        } else {
            lbl_result_->setText(QStringLiteral("连接失败: %1").arg(error));
        }
        probeApi->deleteLater();
    });
}
