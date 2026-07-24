include_directories(${PROTO_BIN_DIR})

add_executable(alarm_service
    main.cpp
    alarm_service_impl.cpp
)

target_link_libraries(alarm_service
    common
    proto
    ${GRPC_LIBRARIES}
    ${PROTOBUF_LIBRARIES}
    ${MYSQL_LIBRARIES}
    Threads::Threads
)