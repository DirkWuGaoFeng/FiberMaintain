cmake_minimum_required(VERSION 3.21)

# Qt6 光纤维护监控桌面客户端
# 设计意图：仅通过 api_gateway 的 REST(8080)/WS(8081) 访问后端，与 WSL 编译的
# Services 完全解耦，本工程在 Windows 原生编译（Qt 6.10 mingw_64 + MinGW 13.1）。
project(FiberMonitorClient VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

find_package(Qt6 REQUIRED COMPONENTS Widgets Network WebSockets Charts)

file(GLOB_RECURSE APP_SOURCES CONFIGURE_DEPENDS src/*.cpp src/*.h)

add_executable(FiberMonitorClient WIN32
    ${APP_SOURCES}
    resources/resources.qrc
)

target_include_directories(FiberMonitorClient PRIVATE src)

target_link_libraries(FiberMonitorClient PRIVATE
    Qt6::Widgets
    Qt6::Network
    Qt6::WebSockets
    Qt6::Charts
)
