include_directories(${PROTO_BIN_DIR})

find_package(PkgConfig REQUIRED)
pkg_check_modules(MICROHTTPD REQUIRED libmicrohttpd)

add_executable(api_gateway
    main.cpp
    http_server.cpp
    websocket_server.cpp
)

target_link_libraries(api_gateway
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    ${MICROHTTPD_LIBRARIES}
    Threads::Threads
)
