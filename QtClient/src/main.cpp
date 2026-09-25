/**
 * @file main.cpp
 * @author FiberMaintain Team
 * @brief 光纤维护监控桌面客户端程序入口
 *
 * 设计意图：入口只做三件事——构造 QApplication、加载全局 QSS 主题、
 * 显示主窗口。所有连接编排、探测、事件分发都收敛在 MainWindow 内，
 * 保持入口薄而清晰，便于后续接入深色主题或命令行参数时无处可改。
 */

#include "ui/main_window.h"

#include <QApplication>
#include <QFile>

int main(int argc, char* argv[]) {
    QApplication app(argc, argv);
    QApplication::setApplicationName(QStringLiteral("FiberMonitorClient"));
    QApplication::setOrganizationName(QStringLiteral("FiberMaintain"));
    // 关闭主窗口即退出（托盘隐藏逻辑在 MainWindow::closeEvent 内处理）
    QApplication::setQuitOnLastWindowClosed(true);

    // 浅色主题样式表：语义色与图表配色集中在此，资源前缀见 resources.qrc
    if (QFile qss(QStringLiteral(":/style/app.qss")); qss.open(QIODevice::ReadOnly))
        app.setStyleSheet(QString::fromUtf8(qss.readAll()));

    MainWindow window;
    window.show();
    return QApplication::exec();
}
