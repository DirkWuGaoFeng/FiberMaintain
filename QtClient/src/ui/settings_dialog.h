#pragma once
/**
 * @file settings_dialog.h
 * @author FiberMaintain Team
 * @brief 连接与提醒设置对话框
 *
 * 设计意图：WSL IP 会变化，必须支持手填服务器地址并"测试连接"验证；
 * CRITICAL 告警声音提醒默认开启、可关闭（值班场景）。
 */

#include <QDialog>

class ApiClient;
class QLineEdit;
class QCheckBox;
class QLabel;

class SettingsDialog : public QDialog {
    Q_OBJECT
public:
    SettingsDialog(ApiClient* api, const QString& wsUrl, QWidget* parent = nullptr);

    QString serverUrl() const;
    bool soundEnabled() const;

    /// 用当前设置项初始化声音复选框（对话框默认不记住上次状态）
    void setChecked(bool sound_on);

private:
    void onTestConnection();

    ApiClient* api_;
    QString ws_url_;
    QLineEdit* edit_url_;
    QCheckBox* chk_sound_;
    QLabel* lbl_result_;
};
